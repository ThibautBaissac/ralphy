"""PR Agent - Creates Pull Request on GitHub."""

import re
from pathlib import Path
from typing import Optional

from ralphy.agents.base import AgentResult, BaseAgent
from ralphy.claude import ClaudeResponse
from ralphy.config import ProjectConfig


class PRAgent(BaseAgent):
    """Agent that creates the Pull Request."""

    name = "pr-agent"
    prompt_file = "pr-agent.md"

    def __init__(
        self,
        project_path: Path,
        config: ProjectConfig,
        feature_name: Optional[str] = None,
        branch_name: Optional[str] = None,
        **kwargs,
    ):
        super().__init__(project_path, config, **kwargs)
        self.feature_name = feature_name
        self.branch_name = branch_name or self._generate_branch_name()

    def _generate_branch_name(self) -> str:
        """Generates a branch name from the feature name."""
        if self.feature_name:
            # Use feature/<feature-name> format
            name = self.feature_name.lower()
            name = re.sub(r"[^a-z0-9]+", "-", name)
            return f"feature/{name.strip('-')}"
        # Fallback to project name
        name = self.config.name.lower()
        name = re.sub(r"[^a-z0-9]+", "-", name)
        return name.strip("-")

    def build_prompt(self) -> str:
        """Builds the prompt for PR creation."""
        template = self.load_prompt_template()
        if not template:
            self.logger.error("Template pr-agent.md not found")
            return ""

        qa_report = self.read_feature_file("QA_REPORT.md") or "Rapport QA non disponible"

        return self._apply_placeholders(
            template,
            branch_name=self.branch_name,
            qa_report=qa_report,
        )

    def parse_output(self, response: ClaudeResponse) -> AgentResult:
        """Verifies that the PR has been created."""
        pr_url = self._extract_pr_url(response.output)

        if not pr_url:
            return AgentResult(
                success=False,
                output=response.output,
                files_generated=[],
                error_message="PR URL not found in output",
            )

        return AgentResult(
            success=response.exit_signal,
            output=response.output,
            files_generated=[f"PR: {pr_url}"],
            error_message=None if response.exit_signal else "EXIT_SIGNAL not received",
        )

    def _extract_pr_url(self, output: str) -> Optional[str]:
        """Extracts the PR URL from the output."""
        # Pattern for GitHub PR URLs
        patterns = [
            r"https://github\.com/[^\s]+/pull/\d+",
            r"https://github\.com/[^\s]+/compare/[^\s]+",
        ]

        for pattern in patterns:
            match = re.search(pattern, output)
            if match:
                return match.group(0)

        return None
