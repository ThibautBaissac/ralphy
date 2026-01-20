"""Agent de développement - Implémente les tâches définies dans TASKS.md."""

import re
from typing import Tuple

from ralphy.agents.base import AgentResult, BaseAgent
from ralphy.claude import ClaudeResponse


class DevAgent(BaseAgent):
    """Agent qui implémente le code selon TASKS.md."""

    name = "dev-agent"
    prompt_file = "dev_agent.md"

    def build_prompt(self) -> str:
        """Construit le prompt avec les specs et tâches."""
        template = self.load_prompt_template()
        if not template:
            self.logger.error("Template dev_agent.md non trouvé")
            return ""

        spec_content = self.read_file("specs/SPEC.md")
        if not spec_content:
            self.logger.error("specs/SPEC.md non trouvé")
            return ""

        tasks_content = self.read_file("specs/TASKS.md")
        if not tasks_content:
            self.logger.error("specs/TASKS.md non trouvé")
            return ""

        prompt = template.replace("{{project_name}}", self.config.name)
        prompt = prompt.replace("{{language}}", self.config.stack.language)
        prompt = prompt.replace("{{test_command}}", self.config.stack.test_command)
        prompt = prompt.replace("{{spec_content}}", spec_content)
        prompt = prompt.replace("{{tasks_content}}", tasks_content)

        return prompt

    def parse_output(self, response: ClaudeResponse) -> AgentResult:
        """Vérifie que les tâches ont été implémentées."""
        completed, total = self.count_task_status()
        files_generated = self._detect_generated_files()

        if completed < total:
            return AgentResult(
                success=False,
                output=response.output,
                files_generated=files_generated,
                error_message=f"Tâches incomplètes: {completed}/{total}",
            )

        return AgentResult(
            success=response.exit_signal,
            output=response.output,
            files_generated=files_generated,
            error_message=None if response.exit_signal else "EXIT_SIGNAL non reçu",
        )

    def count_task_status(self) -> Tuple[int, int]:
        """Compte les tâches completed et le total."""
        tasks_content = self.read_file("specs/TASKS.md")
        if not tasks_content:
            return 0, 0

        total = tasks_content.count("## Tâche")
        completed = len(re.findall(r"\*\*Statut\*\*:\s*completed", tasks_content, re.IGNORECASE))

        return completed, total

    def _detect_generated_files(self) -> list[str]:
        """Détecte les fichiers générés dans src/ et tests/."""
        files = []

        src_dir = self.project_path / "src"
        if src_dir.exists():
            for f in src_dir.rglob("*"):
                if f.is_file():
                    files.append(str(f.relative_to(self.project_path)))

        tests_dir = self.project_path / "tests"
        if tests_dir.exists():
            for f in tests_dir.rglob("*"):
                if f.is_file() and f.name != "__init__.py":
                    files.append(str(f.relative_to(self.project_path)))

        return files
