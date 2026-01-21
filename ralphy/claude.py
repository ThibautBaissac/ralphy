"""Interface avec Claude Code CLI."""

from __future__ import annotations

import json
import os
import select
import signal
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional

import psutil

from ralphy.logger import get_logger

if TYPE_CHECKING:
    from ralphy.circuit_breaker import CircuitBreaker

EXIT_SIGNAL = "EXIT_SIGNAL: true"
PID_FILE = ".ralphy/claude.pid"

# Intervalle de vérification de l'abort (secondes)
ABORT_CHECK_INTERVAL = 0.1


@dataclass
class TokenUsage:
    """Track token usage from Claude Code CLI."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    context_window: int = 200000
    max_output_tokens: int = 64000

    @property
    def total_tokens(self) -> int:
        """Total tokens used (input + output)."""
        return self.input_tokens + self.output_tokens

    @property
    def context_utilization(self) -> float:
        """Context window utilization as percentage (0-100)."""
        if self.context_window <= 0:
            return 0.0
        return (self.total_tokens / self.context_window) * 100


@dataclass
class ClaudeResponse:
    """Réponse d'une invocation Claude."""

    output: str
    exit_signal: bool
    return_code: int
    timed_out: bool
    circuit_breaker_triggered: bool = False
    token_usage: Optional[TokenUsage] = None
    total_cost_usd: float = 0.0


class JsonStreamParser:
    """Parse Claude Code CLI stream-json output format.

    Handles JSON lines from --output-format=stream-json and extracts:
    - Text content from assistant messages for display/circuit breaker
    - Token usage from result message's usage and modelUsage fields
    """

    def __init__(
        self,
        on_text: Optional[Callable[[str], None]] = None,
        on_usage: Optional[Callable[[TokenUsage, float], None]] = None,
    ):
        self.on_text = on_text
        self.on_usage = on_usage
        self._token_usage = TokenUsage()
        self._total_cost = 0.0

    def parse_line(self, line: str) -> Optional[str]:
        """Parse a JSON line and return extracted text content if any.

        Args:
            line: A single line of JSON output from Claude CLI

        Returns:
            Extracted text content, or None if no text in this line
        """
        line = line.strip()
        if not line:
            return None

        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            # Not valid JSON, might be raw text output
            return line if line else None

        msg_type = data.get("type")

        # Handle assistant messages - extract text content
        if msg_type == "assistant":
            return self._handle_assistant_message(data)

        # Handle result message - extract final usage and cost
        if msg_type == "result":
            self._handle_result_message(data)
            return None

        return None

    def _handle_assistant_message(self, data: dict) -> Optional[str]:
        """Extract text content from assistant message and update token usage."""
        message = data.get("message", {})
        content_blocks = message.get("content", [])

        # Update token usage from message.usage if present
        usage = message.get("usage", {})
        if usage:
            self._update_usage_from_dict(usage)

        # Extract text content
        text_parts = []
        for block in content_blocks:
            if block.get("type") == "text":
                text = block.get("text", "")
                if text:
                    text_parts.append(text)

        if text_parts:
            combined_text = "\n".join(text_parts)
            if self.on_text:
                self.on_text(combined_text)
            return combined_text

        return None

    def _handle_result_message(self, data: dict) -> None:
        """Extract final usage and cost from result message."""
        # Get usage summary
        usage = data.get("usage", {})
        if usage:
            self._update_usage_from_dict(usage)

        # Get model-specific usage for context window size
        model_usage = data.get("modelUsage", {})
        for model_name, model_data in model_usage.items():
            context_window = model_data.get("contextWindow")
            if context_window:
                self._token_usage.context_window = context_window
            break  # Use first model's context window

        # Get total cost
        self._total_cost = data.get("total_cost_usd", 0.0) or data.get("totalCostUsd", 0.0)

        # Trigger callback with final usage
        if self.on_usage:
            self.on_usage(self._token_usage, self._total_cost)

    def _update_usage_from_dict(self, usage: dict) -> None:
        """Update token usage from a usage dictionary."""
        if "input_tokens" in usage:
            self._token_usage.input_tokens = usage["input_tokens"]
        if "inputTokens" in usage:
            self._token_usage.input_tokens = usage["inputTokens"]

        if "output_tokens" in usage:
            self._token_usage.output_tokens = usage["output_tokens"]
        if "outputTokens" in usage:
            self._token_usage.output_tokens = usage["outputTokens"]

        if "cache_read_input_tokens" in usage:
            self._token_usage.cache_read_tokens = usage["cache_read_input_tokens"]
        if "cacheReadInputTokens" in usage:
            self._token_usage.cache_read_tokens = usage["cacheReadInputTokens"]

        if "cache_creation_input_tokens" in usage:
            self._token_usage.cache_creation_tokens = usage["cache_creation_input_tokens"]
        if "cacheCreationInputTokens" in usage:
            self._token_usage.cache_creation_tokens = usage["cacheCreationInputTokens"]

        # Trigger callback on usage update
        if self.on_usage:
            self.on_usage(self._token_usage, self._total_cost)

    @property
    def token_usage(self) -> TokenUsage:
        """Get current token usage."""
        return self._token_usage

    @property
    def total_cost(self) -> float:
        """Get total cost in USD."""
        return self._total_cost


class ClaudeRunner:
    """Exécuteur de commandes Claude Code CLI."""

    def __init__(
        self,
        working_dir: Path,
        timeout: int = 300,
        on_output: Optional[Callable[[str], None]] = None,
        circuit_breaker: Optional[CircuitBreaker] = None,
        model: Optional[str] = None,
        on_token_update: Optional[Callable[[TokenUsage, float], None]] = None,
    ):
        self.working_dir = working_dir
        self.timeout = timeout
        self.on_output = on_output
        self.circuit_breaker = circuit_breaker
        self.model = model
        self.on_token_update = on_token_update
        self._process: Optional[subprocess.Popen] = None
        self._abort_event = threading.Event()
        self._cb_triggered = False
        self._pid_file = working_dir / PID_FILE
        self._json_parser: Optional[JsonStreamParser] = None

    def _save_pid(self, pid: int) -> None:
        """Sauvegarde le PID du process Claude."""
        self._pid_file.parent.mkdir(parents=True, exist_ok=True)
        self._pid_file.write_text(str(pid))

    def _clear_pid(self) -> None:
        """Supprime le fichier PID."""
        if self._pid_file.exists():
            self._pid_file.unlink()

    def _read_output_with_abort_check(
        self,
        output_lines: list[str],
    ) -> None:
        """Lit la sortie du process avec vérification périodique de l'abort.

        Utilise select() sur Unix pour une lecture non-bloquante avec timeout,
        permettant une vérification régulière de l'état d'abort.
        Intègre également le circuit breaker pour détecter les boucles infinies.

        When JSON streaming is enabled, parses JSON lines to extract text content.
        The extracted text is passed to on_output callback and used for circuit breaker.
        """
        # Capture une référence locale pour éviter les race conditions
        # quand le main thread set self._process = None dans le finally
        process = self._process
        if not process or not process.stdout:
            return

        stdout_fd = process.stdout.fileno()
        buffer = ""

        while not self._abort_event.is_set():
            try:
                # Utilise select avec timeout pour vérifier l'abort régulièrement
                if sys.platform != "win32":
                    readable, _, _ = select.select([stdout_fd], [], [], ABORT_CHECK_INTERVAL)
                    if not readable:
                        # Timeout select - vérifie si le process est terminé
                        if process.poll() is not None:
                            break

                        # Vérifie l'inactivité via le circuit breaker
                        if self.circuit_breaker:
                            trigger = self.circuit_breaker.check_inactivity()
                            if trigger:
                                self._cb_triggered = True
                                self._abort_event.set()
                                break
                        continue

                # Lecture non-bloquante
                chunk = process.stdout.read(1)
                if not chunk:
                    # EOF atteint
                    break

                buffer += chunk

                # Si on a une ligne complète, la traiter
                if chunk == "\n":
                    # Parse JSON line if parser is available
                    if self._json_parser:
                        text_content = self._json_parser.parse_line(buffer)
                        if text_content:
                            output_lines.append(text_content + "\n")
                            if self.on_output:
                                self.on_output(text_content)
                            # Enregistre la sortie dans le circuit breaker
                            if self.circuit_breaker:
                                trigger = self.circuit_breaker.record_output(text_content)
                                if trigger:
                                    self._cb_triggered = True
                                    self._abort_event.set()
                                    break
                    else:
                        # Non-JSON mode: process raw line
                        output_lines.append(buffer)
                        if self.on_output:
                            self.on_output(buffer)
                        # Enregistre la sortie dans le circuit breaker
                        if self.circuit_breaker:
                            trigger = self.circuit_breaker.record_output(buffer)
                            if trigger:
                                self._cb_triggered = True
                                self._abort_event.set()
                                break

                    buffer = ""

            except (IOError, OSError, ValueError):
                # ValueError can occur if the file descriptor is closed
                break

        # Flush du buffer restant
        if buffer and not self._abort_event.is_set():
            if self._json_parser:
                text_content = self._json_parser.parse_line(buffer)
                if text_content:
                    output_lines.append(text_content)
                    if self.on_output:
                        self.on_output(text_content)
            else:
                output_lines.append(buffer)
                if self.on_output:
                    self.on_output(buffer)

    def _cb_monitor_task_stagnation(self) -> None:
        """Thread daemon qui vérifie la stagnation des tâches.

        Appelle check_task_stagnation() toutes les secondes et
        déclenche l'abort si le circuit breaker s'ouvre.
        """
        while not self._abort_event.is_set():
            if self.circuit_breaker:
                trigger = self.circuit_breaker.check_task_stagnation()
                if trigger:
                    self._cb_triggered = True
                    self._abort_event.set()
                    break
            # Vérifie toutes les secondes
            self._abort_event.wait(timeout=1.0)

    def run(self, prompt: str) -> ClaudeResponse:
        """Exécute une commande Claude et retourne la réponse."""
        logger = get_logger()
        output_lines: list[str] = []
        timed_out = False

        # Reset l'état d'abort et du circuit breaker
        self._abort_event.clear()
        self._cb_triggered = False

        # Initialize thread references for finally block
        reader_thread = None
        cb_monitor_thread = None

        # Create JSON parser with token update callback
        self._json_parser = JsonStreamParser(
            on_text=None,  # Text handled in _read_output_with_abort_check
            on_usage=self.on_token_update,
        )

        cmd = [
            "claude",
            "--print",
            "--dangerously-skip-permissions",
            "--output-format=stream-json",
            "--verbose",
        ]

        # Add model if specified
        if self.model:
            cmd.extend(["--model", self.model])

        cmd.extend(["-p", prompt])

        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                cwd=self.working_dir,
                bufsize=0,  # Unbuffered pour réactivité
            )

            # Sauvegarde le PID pour permettre l'abort externe
            self._save_pid(self._process.pid)

            # Thread de lecture avec vérification d'abort
            reader_thread = threading.Thread(
                target=self._read_output_with_abort_check,
                args=(output_lines,),
            )
            reader_thread.start()

            # Thread de monitoring du circuit breaker pour la stagnation
            cb_monitor_thread = None
            if self.circuit_breaker:
                cb_monitor_thread = threading.Thread(
                    target=self._cb_monitor_task_stagnation,
                    daemon=True,
                )
                cb_monitor_thread.start()

            # Attente avec vérification périodique de l'abort
            elapsed = 0.0
            while elapsed < self.timeout:
                if self._abort_event.is_set():
                    self._process.kill()
                    if self._cb_triggered:
                        logger.info("Claude interrompu par circuit breaker")
                    else:
                        logger.info("Claude interrompu par abort")
                    break

                try:
                    self._process.wait(timeout=ABORT_CHECK_INTERVAL)
                    break  # Process terminé
                except subprocess.TimeoutExpired:
                    elapsed += ABORT_CHECK_INTERVAL

            # Timeout atteint
            if elapsed >= self.timeout and self._process.poll() is None:
                timed_out = True
                self._process.kill()
                logger.error(f"Claude timeout après {self.timeout}s")

            return_code = self._process.returncode if self._process.returncode is not None else -1
            full_output = "".join(output_lines)
            exit_signal = EXIT_SIGNAL in full_output

            return ClaudeResponse(
                output=full_output,
                exit_signal=exit_signal,
                return_code=return_code,
                timed_out=timed_out,
                circuit_breaker_triggered=self._cb_triggered,
                token_usage=self._json_parser.token_usage if self._json_parser else None,
                total_cost_usd=self._json_parser.total_cost if self._json_parser else 0.0,
            )

        except FileNotFoundError:
            logger.error("Claude Code CLI non trouvé. Vérifiez l'installation.")
            return ClaudeResponse(
                output="",
                exit_signal=False,
                return_code=-1,
                timed_out=False,
            )
        except Exception as e:
            logger.error(f"Erreur Claude: {e}")
            return ClaudeResponse(
                output=str(e),
                exit_signal=False,
                return_code=-1,
                timed_out=False,
            )
        finally:
            # Signal threads to stop first
            self._abort_event.set()
            # Wait for reader thread to finish BEFORE clearing process reference
            # This prevents ValueError when reading from closed file descriptor
            if reader_thread and reader_thread.is_alive():
                reader_thread.join(timeout=2)
            if cb_monitor_thread and cb_monitor_thread.is_alive():
                cb_monitor_thread.join(timeout=1)
            self._clear_pid()
            self._process = None

    def abort(self) -> None:
        """Arrête l'exécution en cours (réactif en ~100ms)."""
        self._abort_event.set()
        if self._process:
            self._process.kill()


def abort_running_claude(project_path: Path) -> bool:
    """Abort un process Claude en cours depuis le fichier PID.

    Vérifie que le processus est bien un processus Claude avant de le tuer
    pour éviter de tuer un processus non lié si le PID a été recyclé.

    Returns True si un process a été tué, False sinon.
    """
    logger = get_logger()
    pid_file = project_path / PID_FILE

    if not pid_file.exists():
        return False

    try:
        pid = int(pid_file.read_text().strip())

        # Verify process exists and is actually Claude
        try:
            process = psutil.Process(pid)
            process_name = process.name().lower()
            # Check if process name contains "claude" or "node" (claude runs via node)
            if "claude" not in process_name and "node" not in process_name:
                logger.warn(f"PID {pid} is not a Claude process ({process_name}), skipping kill")
                pid_file.unlink()
                return False
        except psutil.NoSuchProcess:
            logger.warn(f"Process {pid} no longer exists")
            pid_file.unlink()
            return False

        os.kill(pid, signal.SIGTERM)
        logger.info(f"Process Claude (PID {pid}) interrompu")
        pid_file.unlink()
        return True
    except (ValueError, PermissionError) as e:
        logger.warn(f"Impossible d'interrompre le process: {e}")
        if pid_file.exists():
            pid_file.unlink()
        return False


def check_claude_installed() -> bool:
    """Vérifie si Claude Code CLI est installé."""
    try:
        result = subprocess.run(
            ["claude", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def check_git_installed() -> bool:
    """Vérifie si Git est installé et configuré."""
    try:
        result = subprocess.run(
            ["git", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def check_gh_installed() -> bool:
    """Vérifie si GitHub CLI (gh) est installé."""
    try:
        result = subprocess.run(
            ["gh", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
