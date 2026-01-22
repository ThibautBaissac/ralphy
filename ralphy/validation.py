"""Human validation system for Ralphy."""

from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm

from ralphy.constants import SPEC_PREVIEW_LINES
from ralphy.logger import get_logger


class ValidationResult:
    """Result of a human validation."""

    def __init__(self, approved: bool, comment: Optional[str] = None):
        self.approved = approved
        self.comment = comment


class HumanValidator:
    """Human validation manager."""

    def __init__(self, console: Optional[Console] = None):
        self.console = console or Console()
        self.logger = get_logger()

    def request_validation(
        self,
        title: str,
        files_generated: list[str],
        summary: Optional[str] = None,
    ) -> ValidationResult:
        """Requests human validation."""
        self.logger.newline()
        self.logger.validation("VALIDATION REQUIRED")

        # Display generated files
        self.logger.info("Generated files:")
        for f in files_generated:
            self.logger.file_generated(f)

        # Display summary if provided
        if summary:
            self.logger.newline()
            self.console.print(Panel(summary, title="Summary", border_style="blue"))

        self.logger.newline()

        # Validation prompt (infinite wait)
        approved = Confirm.ask("Approve?", default=True)

        self.logger.newline()

        if approved:
            self.logger.success("Validation approved")
        else:
            self.logger.warn("Validation rejected")

        return ValidationResult(approved=approved)

    def request_spec_validation(
        self,
        feature_dir: Path,
        tasks_count: int,
    ) -> ValidationResult:
        """Requests specification validation.

        Args:
            feature_dir: Path to the feature directory containing SPEC.md and TASKS.md
            tasks_count: Number of tasks in TASKS.md
        """
        files = ["SPEC.md", f"TASKS.md ({tasks_count} tasks)"]

        # Read specification summary
        spec_path = feature_dir / "SPEC.md"
        summary = None
        if spec_path.exists():
            content = spec_path.read_text(encoding="utf-8")
            # Extract first significant lines
            lines = content.split("\n")[:SPEC_PREVIEW_LINES]
            summary = "\n".join(lines)

        return self.request_validation(
            title="Specifications",
            files_generated=files,
            summary=summary,
        )

    def request_qa_validation(
        self,
        feature_dir: Path,
        qa_summary: dict,
    ) -> ValidationResult:
        """Requests QA report validation.

        Args:
            feature_dir: Path to the feature directory containing QA_REPORT.md
            qa_summary: Dictionary with score and critical_issues count
        """
        files = ["QA_REPORT.md"]

        summary_text = f"""Score: {qa_summary.get('score', 'N/A')}
Issues critiques: {qa_summary.get('critical_issues', 0)}"""

        return self.request_validation(
            title="Rapport QA",
            files_generated=files,
            summary=summary_text,
        )
