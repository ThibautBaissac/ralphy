"""Specification Agent - Generates SPEC.md and TASKS.md from PRD.md."""

from pathlib import Path
from typing import Optional

from ralphy.agents.base import AgentResult, BaseAgent
from ralphy.claude import ClaudeResponse
from ralphy.constants import MIN_SPEC_FILE_SIZE_BYTES, MIN_TASKS_FILE_SIZE_BYTES


class SpecAgent(BaseAgent):
    """Agent that generates specifications from a PRD."""

    name = "spec-agent"
    prompt_file = "spec-agent.md"

    def build_prompt(self) -> str:
        """Builds the prompt with PRD content."""
        template = self.load_prompt_template()
        if not template:
            self.logger.error("Template spec-agent.md not found")
            return ""

        prd_content = self.read_feature_file("PRD.md")
        if not prd_content:
            self.logger.error("PRD.md not found in feature directory")
            return ""

        return self._apply_placeholders(template, prd_content=prd_content)

    def parse_output(self, response: ClaudeResponse) -> AgentResult:
        """Verifies that SPEC.md and TASKS.md have been generated."""
        files_generated = []

        spec_path = self.feature_dir / "SPEC.md"
        tasks_path = self.feature_dir / "TASKS.md"

        if spec_path.exists():
            files_generated.append("SPEC.md")
        if tasks_path.exists():
            files_generated.append("TASKS.md")

        if len(files_generated) < 2:
            missing = []
            if "SPEC.md" not in files_generated:
                missing.append("SPEC.md")
            if "TASKS.md" not in files_generated:
                missing.append("TASKS.md")
            return AgentResult(
                success=False,
                output=response.output,
                files_generated=files_generated,
                error_message=f"Missing files: {', '.join(missing)}",
            )

        # Success requires both EXIT_SIGNAL and valid files
        # This ensures protocol consistency with other agents
        spec_has_content = spec_path.stat().st_size > MIN_SPEC_FILE_SIZE_BYTES
        tasks_has_content = tasks_path.stat().st_size > MIN_TASKS_FILE_SIZE_BYTES
        files_valid = spec_has_content and tasks_has_content

        return AgentResult(
            success=response.exit_signal and files_valid,
            output=response.output,
            files_generated=files_generated,
            error_message=None if response.exit_signal else "EXIT_SIGNAL not received",
        )

    def count_tasks(self) -> int:
        """Counts the number of tasks in TASKS.md."""
        tasks_content = self.read_feature_file("TASKS.md")
        if not tasks_content:
            return 0
        return tasks_content.count("## Task")
