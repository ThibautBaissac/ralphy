"""Agent QA - Analyse la qualité et la sécurité du code."""

from ralph.agents.base import AgentResult, BaseAgent
from ralph.claude import ClaudeResponse


class QAAgent(BaseAgent):
    """Agent qui analyse la qualité du code et génère un rapport."""

    name = "qa-agent"
    prompt_file = "qa_agent.md"

    def build_prompt(self) -> str:
        """Construit le prompt pour l'analyse QA."""
        template = self.load_prompt_template()
        if not template:
            self.logger.error("Template qa_agent.md non trouvé")
            return ""

        prompt = template.replace("{{project_name}}", self.config.name)
        prompt = prompt.replace("{{language}}", self.config.stack.language)

        return prompt

    def parse_output(self, response: ClaudeResponse) -> AgentResult:
        """Vérifie que QA_REPORT.md a été généré."""
        files_generated = []

        qa_report_path = self.project_path / "specs" / "QA_REPORT.md"

        if qa_report_path.exists():
            files_generated.append("specs/QA_REPORT.md")
        else:
            return AgentResult(
                success=False,
                output=response.output,
                files_generated=[],
                error_message="QA_REPORT.md non généré",
            )

        return AgentResult(
            success=response.exit_signal,
            output=response.output,
            files_generated=files_generated,
            error_message=None if response.exit_signal else "EXIT_SIGNAL non reçu",
        )

    def get_report_summary(self) -> dict:
        """Extrait un résumé du rapport QA."""
        content = self.read_file("specs/QA_REPORT.md")
        if not content:
            return {"score": "N/A", "critical_issues": 0}

        # Extraction basique du score
        score = "N/A"
        if "Score:" in content or "score:" in content:
            import re
            match = re.search(r"[Ss]core[:\s]+(\d+)/10", content)
            if match:
                score = f"{match.group(1)}/10"

        # Compte les issues critiques
        critical_count = content.lower().count("critique") + content.lower().count("critical")

        return {
            "score": score,
            "critical_issues": critical_count,
        }
