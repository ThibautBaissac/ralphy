"""QA Agent - Analyzes code quality and security."""

import re
from typing import Optional

from ralphy.agents.base import AgentResult, BaseAgent
from ralphy.claude import ClaudeResponse


def parse_qa_report_summary(content: Optional[str]) -> dict:
    """Parse QA report content and extract summary statistics.

    This is a standalone utility function that can be used by both
    QAAgent and Orchestrator to avoid code duplication.

    Args:
        content: The QA report markdown content, or None if not available.

    Returns:
        Dictionary with 'score' (str) and 'critical_issues' (int) keys.
    """
    if not content:
        return {"score": "N/A", "critical_issues": 0}

    # Extract score (format: "Score: X/10" or "score: X/10")
    score = "N/A"
    match = re.search(r"[Ss]core[:\s]+(\d+)/10", content)
    if match:
        score = f"{match.group(1)}/10"

    # Count critical issues (both English "critical" and French "critique")
    content_lower = content.lower()
    critical_count = content_lower.count("critical") + content_lower.count("critique")

    return {
        "score": score,
        "critical_issues": critical_count,
    }


class QAAgent(BaseAgent):
    """Agent that analyzes code quality and generates a report."""

    name = "qa-agent"
    prompt_file = "qa-agent.md"

    def build_prompt(self) -> str:
        """Builds the prompt for QA analysis."""
        template = self.load_prompt_template()
        if not template:
            self.logger.error("Template qa-agent.md not found")
            return ""

        return self._apply_common_placeholders(template)

    def parse_output(self, response: ClaudeResponse) -> AgentResult:
        """Verifies that QA_REPORT.md has been generated."""
        files_generated = []

        qa_report_path = self.feature_dir / "QA_REPORT.md"

        if qa_report_path.exists():
            files_generated.append("QA_REPORT.md")
        else:
            return AgentResult(
                success=False,
                output=response.output,
                files_generated=[],
                error_message="QA_REPORT.md not generated",
            )

        return AgentResult(
            success=response.exit_signal,
            output=response.output,
            files_generated=files_generated,
            error_message=None if response.exit_signal else "EXIT_SIGNAL not received",
        )

    def get_report_summary(self) -> dict:
        """Extracts a summary from the QA report."""
        content = self.read_feature_file("QA_REPORT.md")
        return parse_qa_report_summary(content)
