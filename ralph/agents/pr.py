"""Agent PR - Crée la Pull Request sur GitHub."""

import re
from typing import Optional

from ralph.agents.base import AgentResult, BaseAgent
from ralph.claude import ClaudeResponse


class PRAgent(BaseAgent):
    """Agent qui crée la Pull Request."""

    name = "pr-agent"
    prompt_file = "pr_agent.md"

    def __init__(self, *args, branch_name: Optional[str] = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.branch_name = branch_name or self._generate_branch_name()

    def _generate_branch_name(self) -> str:
        """Génère un nom de branche depuis le nom du projet."""
        name = self.config.name.lower()
        name = re.sub(r"[^a-z0-9]+", "-", name)
        return name.strip("-")

    def build_prompt(self) -> str:
        """Construit le prompt pour la création de PR."""
        template = self.load_prompt_template()
        if not template:
            self.logger.error("Template pr_agent.md non trouvé")
            return ""

        qa_report = self.read_file("specs/QA_REPORT.md") or "Rapport QA non disponible"

        prompt = template.replace("{{project_name}}", self.config.name)
        prompt = prompt.replace("{{branch_name}}", self.branch_name)
        prompt = prompt.replace("{{qa_report}}", qa_report)

        return prompt

    def parse_output(self, response: ClaudeResponse) -> AgentResult:
        """Vérifie que la PR a été créée."""
        pr_url = self._extract_pr_url(response.output)

        if not pr_url:
            return AgentResult(
                success=False,
                output=response.output,
                files_generated=[],
                error_message="URL de PR non trouvée dans la sortie",
            )

        return AgentResult(
            success=response.exit_signal,
            output=response.output,
            files_generated=[f"PR: {pr_url}"],
            error_message=None if response.exit_signal else "EXIT_SIGNAL non reçu",
        )

    def _extract_pr_url(self, output: str) -> Optional[str]:
        """Extrait l'URL de la PR depuis la sortie."""
        # Pattern pour les URLs GitHub PR
        patterns = [
            r"https://github\.com/[^\s]+/pull/\d+",
            r"https://github\.com/[^\s]+/compare/[^\s]+",
        ]

        for pattern in patterns:
            match = re.search(pattern, output)
            if match:
                return match.group(0)

        return None
