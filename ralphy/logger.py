"""Formatted logging for Ralphy with timestamps and colors."""

from datetime import datetime
from typing import Optional

from rich.console import Console
from rich.text import Text


class Logger:
    """Formatted logger with timestamps for the terminal."""

    def __init__(self, console: Optional[Console] = None):
        self.console = console or Console()
        self._live_mode = False

    def set_live_mode(self, active: bool) -> None:
        """Enable/disable live mode (skip output for Rich Live)."""
        self._live_mode = active

    def _timestamp(self) -> str:
        """Returns the formatted timestamp [HH:MM:SS]."""
        return datetime.now().strftime("[%H:%M:%S]")

    def _log(self, message: str, style: str = "") -> None:
        """Logs a message with timestamp."""
        if self._live_mode:
            return
        text = Text()
        text.append(self._timestamp(), style="dim")
        text.append(" ")
        text.append(message, style=style)
        self.console.print(text)

    def info(self, message: str) -> None:
        """Logs an info message."""
        self._log(message)

    def success(self, message: str) -> None:
        """Logs a success message."""
        self._log(message, style="green")

    def warn(self, message: str) -> None:
        """Logs a warning message."""
        self._log(message, style="yellow")

    def error(self, message: str) -> None:
        """Logs an error message."""
        self._log(message, style="red bold")

    def phase(self, phase_name: str) -> None:
        """Logs the start of a phase."""
        self._log(f"Phase: {phase_name}", style="cyan bold")

    def agent(self, agent_name: str, action: str) -> None:
        """Logs an agent action."""
        self._log(f"Agent: {agent_name} {action}", style="blue")

    def validation(self, message: str) -> None:
        """Logs a validation message."""
        text = Text()
        text.append(self._timestamp(), style="dim")
        text.append(" ")
        text.append("=== ", style="yellow bold")
        text.append(message, style="yellow bold")
        text.append(" ===", style="yellow bold")
        self.console.print(text)

    def file_generated(self, filepath: str) -> None:
        """Logs a generated file."""
        self._log(f"  - {filepath}", style="green")

    def task_start(self, task_description: str) -> None:
        """Logs the start of a task (displayed even in live mode)."""
        text = Text()
        text.append(self._timestamp(), style="dim")
        text.append(" ")
        text.append("▶ ", style="blue bold")
        text.append(task_description, style="blue")
        self.console.print(text)

    def task_complete(self, task_description: str) -> None:
        """Logs the end of a task (displayed even in live mode)."""
        text = Text()
        text.append(self._timestamp(), style="dim")
        text.append(" ")
        text.append("✓ ", style="green bold")
        text.append(task_description, style="green")
        self.console.print(text)

    def stream(self, text: str) -> None:
        """Streams text without newline (for agent output)."""
        if self._live_mode:
            return
        self.console.print(text, end="")

    def newline(self) -> None:
        """Displays an empty line."""
        self.console.print()


# Global instance
_logger: Optional[Logger] = None


def get_logger() -> Logger:
    """Returns the global logger instance."""
    global _logger
    if _logger is None:
        _logger = Logger()
    return _logger


def set_logger(logger: Logger) -> None:
    """Sets the global logger instance."""
    global _logger
    _logger = logger
