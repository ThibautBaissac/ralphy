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

        # Compte le total de tâches (format: ### Tâche X.Y ou ## Tâche X)
        total = len(re.findall(r"#{2,3}\s*Tâche\s*[\d.]+", tasks_content))
        # Compte les tâches complétées
        completed = len(re.findall(r"\*\*Statut\*\*:\s*completed", tasks_content, re.IGNORECASE))

        return completed, total

    def get_in_progress_task(self) -> str | None:
        """Retourne l'ID de la tâche en cours (in_progress) s'il y en a une."""
        tasks_content = self.read_file("specs/TASKS.md")
        if not tasks_content:
            return None

        # Cherche une tâche avec statut in_progress
        # Format: ### Tâche 1.9: [Titre]\n- **Statut**: in_progress
        pattern = r"#{2,3}\s*Tâche\s*([\d.]+)[^\n]*\n[^#]*\*\*Statut\*\*:\s*in_progress"
        match = re.search(pattern, tasks_content, re.IGNORECASE)
        if match:
            return match.group(1)
        return None

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
