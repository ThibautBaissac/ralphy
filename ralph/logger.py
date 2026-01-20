"""Logging formaté pour RalphWiggum avec timestamps et couleurs."""

from datetime import datetime
from typing import Optional

from rich.console import Console
from rich.text import Text


class Logger:
    """Logger formaté avec timestamps pour le terminal."""

    def __init__(self, console: Optional[Console] = None):
        self.console = console or Console()
        self._live_mode = False

    def set_live_mode(self, active: bool) -> None:
        """Active/désactive le mode live (skip output pour Rich Live)."""
        self._live_mode = active

    def _timestamp(self) -> str:
        """Retourne le timestamp formaté [HH:MM:SS]."""
        return datetime.now().strftime("[%H:%M:%S]")

    def _log(self, message: str, style: str = "") -> None:
        """Log un message avec timestamp."""
        if self._live_mode:
            return
        text = Text()
        text.append(self._timestamp(), style="dim")
        text.append(" ")
        text.append(message, style=style)
        self.console.print(text)

    def info(self, message: str) -> None:
        """Log un message info."""
        self._log(message)

    def success(self, message: str) -> None:
        """Log un message de succès."""
        self._log(message, style="green")

    def warn(self, message: str) -> None:
        """Log un message warning."""
        self._log(message, style="yellow")

    def error(self, message: str) -> None:
        """Log un message erreur."""
        self._log(message, style="red bold")

    def phase(self, phase_name: str) -> None:
        """Log le début d'une phase."""
        self._log(f"Phase: {phase_name}", style="cyan bold")

    def agent(self, agent_name: str, action: str) -> None:
        """Log une action d'agent."""
        self._log(f"Agent: {agent_name} {action}", style="blue")

    def validation(self, message: str) -> None:
        """Log un message de validation."""
        text = Text()
        text.append(self._timestamp(), style="dim")
        text.append(" ")
        text.append("=== ", style="yellow bold")
        text.append(message, style="yellow bold")
        text.append(" ===", style="yellow bold")
        self.console.print(text)

    def file_generated(self, filepath: str) -> None:
        """Log un fichier généré."""
        self._log(f"  - {filepath}", style="green")

    def stream(self, text: str) -> None:
        """Stream du texte sans newline (pour output agent)."""
        if self._live_mode:
            return
        self.console.print(text, end="")

    def newline(self) -> None:
        """Affiche une ligne vide."""
        self.console.print()


# Instance globale
_logger: Optional[Logger] = None


def get_logger() -> Logger:
    """Retourne l'instance globale du logger."""
    global _logger
    if _logger is None:
        _logger = Logger()
    return _logger


def set_logger(logger: Logger) -> None:
    """Définit l'instance globale du logger."""
    global _logger
    _logger = logger
