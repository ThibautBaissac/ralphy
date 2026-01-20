"""Interface avec Claude Code CLI."""

from __future__ import annotations

import os
import select
import signal
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional

from ralphy.logger import get_logger

if TYPE_CHECKING:
    from ralphy.circuit_breaker import CircuitBreaker

EXIT_SIGNAL = "EXIT_SIGNAL: true"
PID_FILE = ".ralphy/claude.pid"

# Intervalle de vérification de l'abort (secondes)
ABORT_CHECK_INTERVAL = 0.1


@dataclass
class ClaudeResponse:
    """Réponse d'une invocation Claude."""

    output: str
    exit_signal: bool
    return_code: int
    timed_out: bool
    circuit_breaker_triggered: bool = False


class ClaudeRunner:
    """Exécuteur de commandes Claude Code CLI."""

    def __init__(
        self,
        working_dir: Path,
        timeout: int = 300,
        on_output: Optional[Callable[[str], None]] = None,
        circuit_breaker: Optional[CircuitBreaker] = None,
        model: Optional[str] = None,
    ):
        self.working_dir = working_dir
        self.timeout = timeout
        self.on_output = on_output
        self.circuit_breaker = circuit_breaker
        self.model = model
        self._process: Optional[subprocess.Popen] = None
        self._abort_event = threading.Event()
        self._cb_triggered = False
        self._pid_file = working_dir / PID_FILE

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

        cmd = [
            "claude",
            "--print",
            "--dangerously-skip-permissions",
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

            # Signal à la thread de lecture de s'arrêter
            self._abort_event.set()
            reader_thread.join(timeout=2)

            # Attend la fin du thread de monitoring CB
            if cb_monitor_thread and cb_monitor_thread.is_alive():
                cb_monitor_thread.join(timeout=1)

            return_code = self._process.returncode if self._process.returncode is not None else -1
            full_output = "".join(output_lines)
            exit_signal = EXIT_SIGNAL in full_output

            return ClaudeResponse(
                output=full_output,
                exit_signal=exit_signal,
                return_code=return_code,
                timed_out=timed_out,
                circuit_breaker_triggered=self._cb_triggered,
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
            self._abort_event.set()  # S'assure que la thread se termine
            self._clear_pid()
            self._process = None

    def abort(self) -> None:
        """Arrête l'exécution en cours (réactif en ~100ms)."""
        self._abort_event.set()
        if self._process:
            self._process.kill()


def abort_running_claude(project_path: Path) -> bool:
    """Abort un process Claude en cours depuis le fichier PID.

    Returns True si un process a été tué, False sinon.
    """
    logger = get_logger()
    pid_file = project_path / PID_FILE

    if not pid_file.exists():
        return False

    try:
        pid = int(pid_file.read_text().strip())
        os.kill(pid, signal.SIGTERM)
        logger.info(f"Process Claude (PID {pid}) interrompu")
        pid_file.unlink()
        return True
    except (ValueError, ProcessLookupError, PermissionError) as e:
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
