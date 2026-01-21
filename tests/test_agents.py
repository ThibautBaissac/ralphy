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
    prompt_file = "spec_agent.md"  # Use real prompt file for fallback tests

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


class TestDevAgentResume:
    """Tests pour la fonctionnalité de reprise du DevAgent."""

    @pytest.fixture
    def temp_project_with_specs(self):
        """Crée un projet temporaire avec specs et tâches."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_path = Path(tmpdir)
            specs_dir = project_path / "specs"
            specs_dir.mkdir()
            (specs_dir / "SPEC.md").write_text("# Specs\nTest spec content")
            (specs_dir / "TASKS.md").write_text("""# Tâches

### Tâche 1.1: [Migration - Setup]
- **Statut**: completed

### Tâche 1.2: [Model - User]
- **Statut**: completed

### Tâche 1.3: [Controller - Users]
- **Statut**: pending

### Tâche 1.4: [View - Users]
- **Statut**: pending
""")
            yield project_path

    def test_build_prompt_without_resume(self, temp_project_with_specs):
        """Test que build_prompt sans resume n'inclut pas l'instruction de reprise."""
        config = ProjectConfig()
        agent = DevAgent(temp_project_with_specs, config)
        prompt = agent.build_prompt()
        assert "MODE REPRISE" not in prompt

    def test_build_prompt_with_resume(self, temp_project_with_specs):
        """Test que build_prompt avec resume inclut l'instruction de reprise."""
        config = ProjectConfig()
        agent = DevAgent(temp_project_with_specs, config)
        prompt = agent.build_prompt(start_from_task="1.3")
        assert "MODE REPRISE ACTIF" in prompt
        assert "tâche 1.3" in prompt
        assert "Saute toutes les tâches AVANT la tâche 1.3" in prompt

    def test_get_next_pending_task_after_completed(self, temp_project_with_specs):
        """Test de la recherche de la prochaine tâche après une completed."""
        config = ProjectConfig()
        agent = DevAgent(temp_project_with_specs, config)

        # After 1.2 (completed), next pending is 1.3
        next_task = agent.get_next_pending_task_after("1.2")
        assert next_task == "1.3"

    def test_get_next_pending_task_after_returns_same_if_pending(
        self, temp_project_with_specs
    ):
        """Test que get_next_pending_task_after retourne la même si elle est pending."""
        config = ProjectConfig()
        agent = DevAgent(temp_project_with_specs, config)

        # 1.3 is pending, should return it
        next_task = agent.get_next_pending_task_after("1.3")
        assert next_task == "1.3"

    def test_get_next_pending_task_after_skips_to_next_pending(
        self, temp_project_with_specs
    ):
        """Test que get_next_pending_task_after saute les tâches completed."""
        config = ProjectConfig()
        agent = DevAgent(temp_project_with_specs, config)

        # After 1.1, next pending is 1.3 (1.2 is also completed)
        next_task = agent.get_next_pending_task_after("1.1")
        assert next_task == "1.3"

    def test_get_next_pending_task_after_returns_none_when_all_completed(
        self, temp_project_with_specs
    ):
        """Test que get_next_pending_task_after retourne None si toutes complétées."""
        # Update TASKS.md to have all completed
        (temp_project_with_specs / "specs" / "TASKS.md").write_text("""# Tâches

### Tâche 1.1: [Migration - Setup]
- **Statut**: completed

### Tâche 1.2: [Model - User]
- **Statut**: completed
""")
        config = ProjectConfig()
        agent = DevAgent(temp_project_with_specs, config)

        next_task = agent.get_next_pending_task_after("1.2")
        assert next_task is None

    def test_get_next_pending_task_after_with_in_progress(self, temp_project_with_specs):
        """Test avec une tâche in_progress."""
        (temp_project_with_specs / "specs" / "TASKS.md").write_text("""# Tâches

### Tâche 1.1: [Migration - Setup]
- **Statut**: completed

### Tâche 1.2: [Model - User]
- **Statut**: in_progress

### Tâche 1.3: [Controller - Users]
- **Statut**: pending
""")
        config = ProjectConfig()
        agent = DevAgent(temp_project_with_specs, config)

        # 1.2 is in_progress, should return it
        next_task = agent.get_next_pending_task_after("1.2")
        assert next_task == "1.2"

        # After 1.1, next non-completed is 1.2 (in_progress)
        next_task = agent.get_next_pending_task_after("1.1")
        assert next_task == "1.2"


class TestCustomPromptLoading:
    """Tests pour le chargement des prompts personnalisés."""

    @pytest.fixture
    def temp_project(self):
        """Crée un projet temporaire."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_path = Path(tmpdir)
            (project_path / "PRD.md").write_text("# Test PRD")
            yield project_path

    def test_loads_custom_prompt_when_present(self, temp_project):
        """Test que load_prompt_template charge un prompt custom valide."""
        # Crée un prompt custom valide
        prompts_dir = temp_project / ".ralphy" / "prompts"
        prompts_dir.mkdir(parents=True)

        custom_content = """# Custom Spec Agent Prompt

This is a custom prompt for the spec agent.
It must be at least 100 characters long to pass validation.
It also needs to contain the EXIT_SIGNAL instruction.

When done, output EXIT_SIGNAL: true to indicate completion.
"""
        (prompts_dir / "spec_agent.md").write_text(custom_content)

        config = ProjectConfig()
        agent = ConcreteAgent(temp_project, config)
        loaded = agent.load_prompt_template()

        assert loaded == custom_content

    def test_falls_back_to_default_when_no_custom(self, temp_project):
        """Test que load_prompt_template utilise le défaut si pas de custom."""
        config = ProjectConfig()
        agent = ConcreteAgent(temp_project, config)
        loaded = agent.load_prompt_template()

        # Should load from package (spec_agent.md exists in ralphy/prompts/)
        assert len(loaded) > 0
        assert "EXIT_SIGNAL" in loaded

    def test_validates_custom_prompt_has_exit_signal(self, temp_project):
        """Test que le prompt custom est rejeté si EXIT_SIGNAL manque."""
        prompts_dir = temp_project / ".ralphy" / "prompts"
        prompts_dir.mkdir(parents=True)

        # Prompt sans EXIT_SIGNAL (mais assez long)
        invalid_content = """# Custom Spec Agent Prompt

This is a custom prompt that is missing the required exit signal.
It has more than 100 characters but the validation should fail
because it doesn't tell the agent how to signal completion.
"""
        (prompts_dir / "spec_agent.md").write_text(invalid_content)

        config = ProjectConfig()
        agent = ConcreteAgent(temp_project, config)
        loaded = agent.load_prompt_template()

        # Should fallback to default (from package)
        assert "EXIT_SIGNAL" in loaded
        assert loaded != invalid_content

    def test_validates_custom_prompt_not_empty(self, temp_project):
        """Test que le prompt custom est rejeté si vide ou trop court."""
        prompts_dir = temp_project / ".ralphy" / "prompts"
        prompts_dir.mkdir(parents=True)

        # Prompt trop court
        short_content = "Short prompt EXIT_SIGNAL"
        (prompts_dir / "spec_agent.md").write_text(short_content)

        config = ProjectConfig()
        agent = ConcreteAgent(temp_project, config)
        loaded = agent.load_prompt_template()

        # Should fallback to default
        assert len(loaded) > 100
        assert loaded != short_content

    def test_validates_custom_prompt_empty_file(self, temp_project):
        """Test que le prompt custom est rejeté si fichier vide."""
        prompts_dir = temp_project / ".ralphy" / "prompts"
        prompts_dir.mkdir(parents=True)

        (prompts_dir / "spec_agent.md").write_text("")

        config = ProjectConfig()
        agent = ConcreteAgent(temp_project, config)
        loaded = agent.load_prompt_template()

        # Should fallback to default
        assert len(loaded) > 0


class TestValidatePrompt:
    """Tests unitaires pour _validate_prompt."""

    @pytest.fixture
    def temp_project(self):
        """Crée un projet temporaire."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_valid_prompt_passes(self, temp_project):
        """Test qu'un prompt valide passe la validation."""
        config = ProjectConfig()
        agent = ConcreteAgent(temp_project, config)

        valid_content = "A" * 100 + " EXIT_SIGNAL"
        assert agent._validate_prompt(valid_content) is True

    def test_short_prompt_fails(self, temp_project):
        """Test qu'un prompt trop court échoue."""
        config = ProjectConfig()
        agent = ConcreteAgent(temp_project, config)

        short_content = "Short EXIT_SIGNAL"
        assert agent._validate_prompt(short_content) is False

    def test_missing_exit_signal_fails(self, temp_project):
        """Test qu'un prompt sans EXIT_SIGNAL échoue."""
        config = ProjectConfig()
        agent = ConcreteAgent(temp_project, config)

        no_signal = "A" * 200  # Long enough but no EXIT_SIGNAL
        assert agent._validate_prompt(no_signal) is False

    def test_empty_prompt_fails(self, temp_project):
        """Test qu'un prompt vide échoue."""
        config = ProjectConfig()
        agent = ConcreteAgent(temp_project, config)

        assert agent._validate_prompt("") is False
        assert agent._validate_prompt(None) is False
