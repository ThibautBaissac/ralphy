"""Agent de spécification - Génère SPEC.md et TASKS.md depuis PRD.md."""

from pathlib import Path
from typing import Optional

from ralphy.agents.base import AgentResult, BaseAgent
from ralphy.claude import ClaudeResponse


class SpecAgent(BaseAgent):
    """Agent qui génère les spécifications depuis un PRD."""

    name = "spec-agent"
    prompt_file = "spec_agent.md"

    def build_prompt(self) -> str:
        """Construit le prompt avec le contenu du PRD."""
        template = self.load_prompt_template()
        if not template:
            self.logger.error("Template spec_agent.md non trouvé")
            return ""

        prd_content = self.read_feature_file("PRD.md")
        if not prd_content:
            self.logger.error("PRD.md non trouvé dans le dossier feature")
            return ""

        return self._apply_placeholders(template, prd_content=prd_content)

    def parse_output(self, response: ClaudeResponse) -> AgentResult:
        """Vérifie que SPEC.md et TASKS.md ont été générés."""
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
                error_message=f"Fichiers manquants: {', '.join(missing)}",
            )

        # Success requires both EXIT_SIGNAL and valid files
        # This ensures protocol consistency with other agents
        spec_has_content = spec_path.stat().st_size > 1000
        tasks_has_content = tasks_path.stat().st_size > 500
        files_valid = spec_has_content and tasks_has_content

        return AgentResult(
            success=response.exit_signal and files_valid,
            output=response.output,
            files_generated=files_generated,
            error_message=None if response.exit_signal else "EXIT_SIGNAL non reçu",
        )

    def count_tasks(self) -> int:
        """Compte le nombre de tâches dans TASKS.md."""
        tasks_content = self.read_feature_file("TASKS.md")
        if not tasks_content:
            return 0
        return tasks_content.count("## Tâche")
