"""Tests pour les agents."""

import tempfile
from pathlib import Path

import pytest

from ralphy.agents.base import AgentResult, BaseAgent
from ralphy.agents.dev import DevAgent
from ralphy.agents.spec import SpecAgent
from ralphy.claude import ClaudeResponse
from ralphy.config import ProjectConfig


class ConcreteAgent(BaseAgent):
    """Agent concret pour les tests."""

    name = "test-agent"
    prompt_file = "test.md"

    def build_prompt(self) -> str:
        return "Test prompt"

    def parse_output(self, response: ClaudeResponse) -> AgentResult:
        return AgentResult(
            success=response.exit_signal,
            output=response.output,
            files_generated=[],
        )


class TestBaseAgent:
    """Tests pour BaseAgent."""

    @pytest.fixture
    def temp_project(self):
        """Crée un projet temporaire."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_path = Path(tmpdir)
            (project_path / "PRD.md").write_text("# Test PRD")
            yield project_path

    def test_read_file(self, temp_project):
        """Test de lecture de fichier."""
        config = ProjectConfig()
        agent = ConcreteAgent(temp_project, config)
        content = agent.read_file("PRD.md")
        assert content == "# Test PRD"

    def test_read_missing_file(self, temp_project):
        """Test de lecture de fichier manquant."""
        config = ProjectConfig()
        agent = ConcreteAgent(temp_project, config)
        content = agent.read_file("MISSING.md")
        assert content is None


class TestSpecAgent:
    """Tests pour SpecAgent."""

    @pytest.fixture
    def temp_project(self):
        """Crée un projet temporaire avec PRD."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_path = Path(tmpdir)
            (project_path / "PRD.md").write_text("# Test PRD\n\n## Objectif\nTest")
            (project_path / "specs").mkdir()
            yield project_path

    def test_count_tasks(self, temp_project):
        """Test du comptage de tâches."""
        config = ProjectConfig()
        agent = SpecAgent(temp_project, config)

        # Crée un fichier TASKS.md
        tasks_content = """# Tâches
## Tâche 1: Setup
- **Statut**: pending

## Tâche 2: Implementation
- **Statut**: pending

## Tâche 3: Tests
- **Statut**: pending
"""
        (temp_project / "specs" / "TASKS.md").write_text(tasks_content)

        count = agent.count_tasks()
        assert count == 3


class TestDevAgent:
    """Tests pour DevAgent."""

    @pytest.fixture
    def temp_project(self):
        """Crée un projet temporaire avec specs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_path = Path(tmpdir)
            specs_dir = project_path / "specs"
            specs_dir.mkdir()
            (specs_dir / "SPEC.md").write_text("# Specs")
            (specs_dir / "TASKS.md").write_text("""# Tâches
## Tâche 1: Test
- **Statut**: completed

## Tâche 2: Test2
- **Statut**: pending
""")
            yield project_path

    def test_count_task_status(self, temp_project):
        """Test du comptage des statuts de tâches."""
        config = ProjectConfig()
        agent = DevAgent(temp_project, config)

        completed, total = agent.count_task_status()
        assert completed == 1
        assert total == 2

    def test_count_task_status_with_triple_hash(self, temp_project):
        """Test du comptage avec format ### Tâche (généré par spec-agent)."""
        (temp_project / "specs" / "TASKS.md").write_text("""# Tâches
### Tâche 1.1: [Migration - Setup]
- **Statut**: completed

### Tâche 1.2: [Model - User]
- **Statut**: in_progress

### Tâche 1.3: [Controller - Users]
- **Statut**: pending
""")
        config = ProjectConfig()
        agent = DevAgent(temp_project, config)

        completed, total = agent.count_task_status()
        assert total == 3
        assert completed == 1

    def test_get_in_progress_task(self, temp_project):
        """Test de la détection d'une tâche in_progress."""
        (temp_project / "specs" / "TASKS.md").write_text("""# Tâches
### Tâche 1.1: [Migration - Setup]
- **Statut**: completed

### Tâche 1.2: [Model - User]
- **Statut**: in_progress

### Tâche 1.3: [Controller - Users]
- **Statut**: pending
""")
        config = ProjectConfig()
        agent = DevAgent(temp_project, config)

        in_progress = agent.get_in_progress_task()
        assert in_progress == "1.2"

    def test_get_in_progress_task_none(self, temp_project):
        """Test quand aucune tâche n'est in_progress."""
        config = ProjectConfig()
        agent = DevAgent(temp_project, config)

        in_progress = agent.get_in_progress_task()
        assert in_progress is None
