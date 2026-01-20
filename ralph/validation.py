"""Système de validation humaine pour RalphWiggum."""

from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm

from ralph.logger import get_logger


class ValidationResult:
    """Résultat d'une validation humaine."""

    def __init__(self, approved: bool, comment: Optional[str] = None):
        self.approved = approved
        self.comment = comment


class HumanValidator:
    """Gestionnaire de validation humaine."""

    def __init__(self, console: Optional[Console] = None):
        self.console = console or Console()
        self.logger = get_logger()

    def request_validation(
        self,
        title: str,
        files_generated: list[str],
        summary: Optional[str] = None,
    ) -> ValidationResult:
        """Demande une validation humaine."""
        self.logger.newline()
        self.logger.validation("VALIDATION REQUISE")

        # Affiche les fichiers générés
        self.logger.info("Fichiers générés:")
        for f in files_generated:
            self.logger.file_generated(f)

        # Affiche le résumé si fourni
        if summary:
            self.logger.newline()
            self.console.print(Panel(summary, title="Résumé", border_style="blue"))

        self.logger.newline()

        # Prompt de validation (attente infinie)
        approved = Confirm.ask("Approuver ?", default=True)

        self.logger.newline()

        if approved:
            self.logger.success("Validation approuvée")
        else:
            self.logger.warn("Validation rejetée")

        return ValidationResult(approved=approved)

    def request_spec_validation(
        self,
        project_path: Path,
        tasks_count: int,
    ) -> ValidationResult:
        """Demande validation des spécifications."""
        files = ["specs/SPEC.md", f"specs/TASKS.md ({tasks_count} tâches)"]

        # Lecture du résumé des specs
        spec_path = project_path / "specs" / "SPEC.md"
        summary = None
        if spec_path.exists():
            content = spec_path.read_text(encoding="utf-8")
            # Extrait les premières lignes significatives
            lines = content.split("\n")[:20]
            summary = "\n".join(lines)

        return self.request_validation(
            title="Spécifications",
            files_generated=files,
            summary=summary,
        )

    def request_qa_validation(
        self,
        project_path: Path,
        qa_summary: dict,
    ) -> ValidationResult:
        """Demande validation du rapport QA."""
        files = ["specs/QA_REPORT.md"]

        summary_text = f"""Score: {qa_summary.get('score', 'N/A')}
Issues critiques: {qa_summary.get('critical_issues', 0)}"""

        return self.request_validation(
            title="Rapport QA",
            files_generated=files,
            summary=summary_text,
        )
