"""Interface with Claude Code CLI."""

from __future__ import annotations

import json
import os
import select
import signal
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from io import StringIO
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional

import psutil

from ralphy.constants import DEFAULT_CONTEXT_WINDOW, DEFAULT_MAX_OUTPUT_TOKENS
from ralphy.logger import get_logger

if TYPE_CHECKING:
    from ralphy.circuit_breaker import CircuitBreaker

EXIT_SIGNAL = "EXIT_SIGNAL: true"
PID_FILE = ".ralphy/claude.pid"

# Abort check interval (seconds)
ABORT_CHECK_INTERVAL = 0.1


class ProcessManager:
    """Manages subprocess lifecycle (creation, PID tracking, cleanup).

    Encapsulates all subprocess management concerns:
    - Process creation with proper configuration
    - PID file management for external abort capability
    - Process cleanup and resource release
    """

    def __init__(self, working_dir: Path, pid_file: Path):
        """Initialize the process manager.

        Args:
            working_dir: Working directory for subprocess execution
            pid_file: Path to store the process PID
        """
        self._working_dir = working_dir
        self._pid_file = pid_file
        self._process: Optional[subprocess.Popen] = None

    def start(self, cmd: list[str]) -> subprocess.Popen:
        """Start a subprocess with the given command.

        Args:
            cmd: Command and arguments to execute

        Returns:
            The started subprocess
        """
        self._process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=self._working_dir,
            bufsize=0,  # Unbuffered for responsiveness
        )
        self._save_pid(self._process.pid)
        return self._process

    def _save_pid(self, pid: int) -> None:
        """Save the PID of the process for external abort capability."""
        self._pid_file.parent.mkdir(parents=True, exist_ok=True)
        self._pid_file.write_text(str(pid))

    def cleanup(self) -> None:
        """Clean up process resources and PID file."""
        self._clear_pid()
        if self._process and self._process.stdout:
            try:
                self._process.stdout.close()
            except Exception:
                pass
        self._process = None

    def _clear_pid(self) -> None:
        """Remove the PID file."""
        if self._pid_file.exists():
            self._pid_file.unlink()

    def kill(self) -> None:
        """Kill the running process."""
        if self._process:
            self._process.kill()

    def wait(self, timeout: Optional[float] = None) -> Optional[int]:
        """Wait for process to complete.

        Args:
            timeout: Maximum time to wait in seconds

        Returns:
            Return code, or None if timeout expired

        Raises:
            subprocess.TimeoutExpired: If timeout expires
        """
        if self._process:
            self._process.wait(timeout=timeout)
            return self._process.returncode
        return None

    def poll(self) -> Optional[int]:
        """Check if process has terminated.

        Returns:
            Return code if terminated, None otherwise
        """
        if self._process:
            return self._process.poll()
        return None

    @property
    def process(self) -> Optional[subprocess.Popen]:
        """Get the current subprocess."""
        return self._process

    @property
    def return_code(self) -> int:
        """Get the return code of the process.

        Returns:
            The return code, or -1 if process not started or not terminated
        """
        if self._process and self._process.returncode is not None:
            return self._process.returncode
        return -1


class StreamReader:
    """Non-blocking output reader with abort support.

    Handles reading subprocess output using select() on Unix,
    enabling regular abort state checking and circuit breaker integration.
    """

    def __init__(
        self,
        abort_event: threading.Event,
        json_parser: Optional[JsonStreamParser],
        circuit_breaker: Optional[CircuitBreaker],
        on_output: Optional[Callable[[str], None]],
        on_cb_trigger: Callable[[], None],
    ):
        """Initialize the stream reader.

        Args:
            abort_event: Threading event to signal abort
            json_parser: Optional JSON parser for stream-json format
            circuit_breaker: Optional circuit breaker for loop detection
            on_output: Callback for processed output text
            on_cb_trigger: Callback when circuit breaker triggers
        """
        self._abort_event = abort_event
        self._json_parser = json_parser
        self._circuit_breaker = circuit_breaker
        self._on_output = on_output
        self._on_cb_trigger = on_cb_trigger

    def read_lines(self, process: subprocess.Popen) -> list[str]:
        """Read output lines from process with abort checking.

        Uses select() for non-blocking reading with timeout, enabling
        regular abort state checking. Integrates circuit breaker to
        detect infinite loops.

        When JSON streaming is enabled, parses JSON lines to extract text content.
        The extracted text is passed to on_output callback and used for circuit breaker.

        Args:
            process: The subprocess to read from

        Returns:
            List of output lines (text content if JSON parsing enabled)
        """
        output_lines: list[str] = []

        if not process or not process.stdout:
            return output_lines

        stdout_fd = process.stdout.fileno()
        buffer = StringIO()

        while not self._abort_event.is_set():
            try:
                # Use select with timeout to check abort regularly
                if sys.platform != "win32":
                    readable, _, _ = select.select([stdout_fd], [], [], ABORT_CHECK_INTERVAL)
                    if not readable:
                        # Select timeout - check if process terminated
                        if process.poll() is not None:
                            break

                        # Check inactivity via circuit breaker
                        if self._circuit_breaker:
                            trigger = self._circuit_breaker.check_inactivity()
                            if trigger:
                                self._on_cb_trigger()
                                self._abort_event.set()
                                break
                        continue

                # Non-blocking read
                chunk = process.stdout.read(1)
                if not chunk:
                    # EOF reached
                    break

                buffer.write(chunk)

                # If we have a complete line, process it
                if chunk == "\n":
                    line_content = buffer.getvalue()
                    self._process_line(line_content, output_lines)
                    buffer = StringIO()

            except (IOError, OSError, ValueError):
                # ValueError can occur if the file descriptor is closed
                break

        # Flush remaining buffer
        if buffer.tell() > 0 and not self._abort_event.is_set():
            remaining = buffer.getvalue()
            self._process_line(remaining, output_lines, add_newline=False)

        return output_lines

    def _process_line(
        self, line_content: str, output_lines: list[str], add_newline: bool = True
    ) -> None:
        """Process a single line of output.

        Args:
            line_content: The line content to process
            output_lines: List to append processed output to
            add_newline: Whether to add newline to text content
        """
        if self._json_parser:
            text_content = self._json_parser.parse_line(line_content)
            # Reset circuit breaker inactivity for ANY valid JSON line,
            # not just text content. This ensures "system" init messages
            # count as activity to prevent false inactivity triggers.
            if self._circuit_breaker and line_content.strip():
                trigger = self._circuit_breaker.record_output(text_content or "[system]")
                if trigger:
                    self._on_cb_trigger()
                    self._abort_event.set()
                    return
            if text_content:
                output_lines.append(text_content + "\n" if add_newline else text_content)
                if self._on_output:
                    self._on_output(text_content)
        else:
            # Non-JSON mode: process raw line
            output_lines.append(line_content)
            if self._on_output:
                self._on_output(line_content)
            # Record output in circuit breaker
            if self._circuit_breaker:
                trigger = self._circuit_breaker.record_output(line_content)
                if trigger:
                    self._on_cb_trigger()
                    self._abort_event.set()


@dataclass
class TokenUsage:
    """Track token usage from Claude Code CLI."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    context_window: int = DEFAULT_CONTEXT_WINDOW
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS

    @property
    def total_tokens(self) -> int:
        """Total tokens used (input + output + cache read).

        Cache read tokens count toward context utilization because
        they represent tokens that were read from the prompt cache.
        """
        return self.input_tokens + self.output_tokens + self.cache_read_tokens

    @property
    def context_utilization(self) -> float:
        """Context window utilization as percentage (0-100).

        Based on total tokens (input + output + cache read) vs context window.
        """
        if self.context_window <= 0:
            return 0.0
        return (self.total_tokens / self.context_window) * 100


@dataclass
class ClaudeResponse:
    """Response from a Claude invocation."""

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
    """Executor for Claude Code CLI commands.

    Coordinates subprocess execution, output streaming, and circuit breaker
    monitoring. Delegates subprocess lifecycle to ProcessManager and output
    reading to StreamReader.
    """

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
        self._abort_event = threading.Event()
        self._cb_triggered = False
        self._cb_lock = threading.Lock()  # Protects _cb_triggered across threads
        self._process_manager = ProcessManager(working_dir, working_dir / PID_FILE)
        self._json_parser: Optional[JsonStreamParser] = None

    def _on_cb_trigger(self) -> None:
        """Callback when circuit breaker triggers."""
        with self._cb_lock:
            self._cb_triggered = True

    def _cb_monitor_task_stagnation(self) -> None:
        """Daemon thread that monitors task stagnation.

        Calls check_task_stagnation() every second and
        triggers abort if circuit breaker opens.
        """
        while not self._abort_event.is_set():
            if self.circuit_breaker:
                trigger = self.circuit_breaker.check_task_stagnation()
                if trigger:
                    self._on_cb_trigger()
                    self._abort_event.set()
                    break
            # Check every second
            self._abort_event.wait(timeout=1.0)

    def _build_command(self, prompt: str) -> list[str]:
        """Build the Claude CLI command.

        Args:
            prompt: The prompt to send to Claude

        Returns:
            List of command arguments
        """
        cmd = [
            "claude",
            "--print",
            "--dangerously-skip-permissions",
            "--output-format=stream-json",
            "--verbose",
        ]

        if self.model:
            cmd.extend(["--model", self.model])

        cmd.extend(["-p", prompt])
        return cmd

    def run(self, prompt: str) -> ClaudeResponse:
        """Executes a Claude command and returns the response."""
        logger = get_logger()
        timed_out = False

        # Reset abort state and circuit breaker
        self._abort_event.clear()
        with self._cb_lock:
            self._cb_triggered = False

        # Initialize thread references for finally block
        reader_thread = None
        cb_monitor_thread = None

        # Create JSON parser with token update callback
        self._json_parser = JsonStreamParser(
            on_text=None,  # Text handled in StreamReader
            on_usage=self.on_token_update,
        )

        # Create stream reader
        stream_reader = StreamReader(
            abort_event=self._abort_event,
            json_parser=self._json_parser,
            circuit_breaker=self.circuit_breaker,
            on_output=self.on_output,
            on_cb_trigger=self._on_cb_trigger,
        )

        cmd = self._build_command(prompt)

        try:
            process = self._process_manager.start(cmd)

            # Reader thread with abort verification
            output_lines: list[str] = []
            reader_thread = threading.Thread(
                target=lambda: output_lines.extend(stream_reader.read_lines(process)),
            )
            reader_thread.start()

            # Circuit breaker monitoring thread for stagnation
            cb_monitor_thread = None
            if self.circuit_breaker:
                cb_monitor_thread = threading.Thread(
                    target=self._cb_monitor_task_stagnation,
                    daemon=True,
                )
                cb_monitor_thread.start()

            # Wait with periodic abort verification
            elapsed = 0.0
            while elapsed < self.timeout:
                if self._abort_event.is_set():
                    self._process_manager.kill()
                    self._process_manager.wait()  # Reap process to get proper return code
                    with self._cb_lock:
                        cb_triggered = self._cb_triggered
                    if cb_triggered:
                        logger.info("Claude interrupted by circuit breaker")
                    else:
                        logger.info("Claude interrupted by abort")
                    break

                try:
                    self._process_manager.wait(timeout=ABORT_CHECK_INTERVAL)
                    break  # Process terminated
                except subprocess.TimeoutExpired:
                    elapsed += ABORT_CHECK_INTERVAL

            # Timeout reached
            if elapsed >= self.timeout and self._process_manager.poll() is None:
                timed_out = True
                self._process_manager.kill()
                self._process_manager.wait()  # Reap process to get proper return code
                logger.error(f"Claude timeout after {self.timeout}s")

            # Wait for reader thread to complete before accessing output_lines
            if reader_thread and reader_thread.is_alive():
                reader_thread.join(timeout=2)

            return_code = self._process_manager.return_code
            full_output = "".join(output_lines)
            exit_signal = EXIT_SIGNAL in full_output

            with self._cb_lock:
                cb_triggered = self._cb_triggered

            return ClaudeResponse(
                output=full_output,
                exit_signal=exit_signal,
                return_code=return_code,
                timed_out=timed_out,
                circuit_breaker_triggered=cb_triggered,
                token_usage=self._json_parser.token_usage if self._json_parser else None,
                total_cost_usd=self._json_parser.total_cost if self._json_parser else 0.0,
            )

        except FileNotFoundError:
            logger.error("Claude Code CLI not found. Check installation.")
            return ClaudeResponse(
                output="",
                exit_signal=False,
                return_code=-1,
                timed_out=False,
            )
        except Exception as e:
            logger.error(f"Claude error: {e}")
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
            self._process_manager.cleanup()

    def abort(self) -> None:
        """Stops current execution (responsive in ~100ms)."""
        self._abort_event.set()
        self._process_manager.kill()


def abort_running_claude(project_path: Path) -> bool:
    """Aborts a running Claude process from the PID file.

    Verifies that the process is actually a Claude process before killing it
    to avoid killing an unrelated process if the PID was recycled.

    Returns True if a process was killed, False otherwise.
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
        logger.info(f"Claude process (PID {pid}) interrupted")
        pid_file.unlink()
        return True
    except (ValueError, PermissionError) as e:
        logger.warn(f"Failed to interrupt process: {e}")
        if pid_file.exists():
            pid_file.unlink()
        return False


def check_claude_installed() -> bool:
    """Checks if Claude Code CLI is installed."""
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
    """Checks if Git is installed and configured."""
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
    """Checks if GitHub CLI (gh) is installed."""
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
