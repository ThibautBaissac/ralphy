"""Tests for agents."""

import tempfile
from pathlib import Path

import pytest

from ralphy.agents.base import AgentResult, BaseAgent
from ralphy.agents.dev import DevAgent
from ralphy.agents.spec import SpecAgent
from ralphy.claude import ClaudeResponse
from ralphy.config import ProjectConfig, StackConfig


class ConcreteAgent(BaseAgent):
    """Concrete agent for testing."""

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
    """Tests for BaseAgent."""

    @pytest.fixture
    def temp_project(self):
        """Creates a temporary project."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_path = Path(tmpdir)
            (project_path / "PRD.md").write_text("# Test PRD")
            yield project_path

    def test_read_file(self, temp_project):
        """Tests file reading."""
        config = ProjectConfig()
        agent = ConcreteAgent(temp_project, config)
        content = agent.read_file("PRD.md")
        assert content == "# Test PRD"

    def test_read_missing_file(self, temp_project):
        """Tests reading a missing file."""
        config = ProjectConfig()
        agent = ConcreteAgent(temp_project, config)
        content = agent.read_file("MISSING.md")
        assert content is None

    def test_agent_stores_model_parameter(self, temp_project):
        """Tests that agent stores the model parameter."""
        config = ProjectConfig()
        agent = ConcreteAgent(temp_project, config, model="opus")
        assert agent.model == "opus"

    def test_agent_model_defaults_to_none(self, temp_project):
        """Tests that agent defaults to model=None."""
        config = ProjectConfig()
        agent = ConcreteAgent(temp_project, config)
        assert agent.model is None


class TestSpecAgent:
    """Tests for SpecAgent."""

    @pytest.fixture
    def temp_project(self):
        """Creates a temporary project with PRD in feature directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_path = Path(tmpdir)
            feature_dir = project_path / "docs" / "features" / "test-feature"
            feature_dir.mkdir(parents=True)
            (feature_dir / "PRD.md").write_text("# Test PRD\n\n## Objectif\nTest")
            yield project_path, feature_dir

    def test_count_tasks(self, temp_project):
        """Tests task counting."""
        project_path, feature_dir = temp_project
        config = ProjectConfig()
        agent = SpecAgent(project_path, config, feature_dir=feature_dir)

        # Creates a TASKS.md file
        tasks_content = """# Tasks
## Task 1: Setup
- **Status**: pending

## Task 2: Implementation
- **Status**: pending

## Task 3: Tests
- **Status**: pending
"""
        (feature_dir / "TASKS.md").write_text(tasks_content)

        count = agent.count_tasks()
        assert count == 3


class TestDevAgent:
    """Tests pour DevAgent."""

    @pytest.fixture
    def temp_project(self):
        """Crée un projet temporaire avec specs dans feature directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_path = Path(tmpdir)
            feature_dir = project_path / "docs" / "features" / "test-feature"
            feature_dir.mkdir(parents=True)
            (feature_dir / "SPEC.md").write_text("# Specs")
            (feature_dir / "TASKS.md").write_text("""# Tasks
## Task 1: Test
- **Status**: completed

## Task 2: Test2
- **Status**: pending
""")
            yield project_path, feature_dir

    def test_count_task_status(self, temp_project):
        """Test du comptage des statuts de tâches."""
        project_path, feature_dir = temp_project
        config = ProjectConfig()
        agent = DevAgent(project_path, config, feature_dir=feature_dir)

        completed, total = agent.count_task_status()
        assert completed == 1
        assert total == 2

    def test_count_task_status_with_triple_hash(self, temp_project):
        """Test du comptage avec format ### Tâche (généré par spec-agent)."""
        project_path, feature_dir = temp_project
        (feature_dir / "TASKS.md").write_text("""# Tasks
### Task 1.1: [Migration - Setup]
- **Status**: completed

### Task 1.2: [Model - User]
- **Status**: in_progress

### Task 1.3: [Controller - Users]
- **Status**: pending
""")
        config = ProjectConfig()
        agent = DevAgent(project_path, config, feature_dir=feature_dir)

        completed, total = agent.count_task_status()
        assert total == 3
        assert completed == 1

    def test_get_in_progress_task(self, temp_project):
        """Test de la détection d'une tâche in_progress."""
        project_path, feature_dir = temp_project
        (feature_dir / "TASKS.md").write_text("""# Tasks
### Task 1.1: [Migration - Setup]
- **Status**: completed

### Task 1.2: [Model - User]
- **Status**: in_progress

### Task 1.3: [Controller - Users]
- **Status**: pending
""")
        config = ProjectConfig()
        agent = DevAgent(project_path, config, feature_dir=feature_dir)

        in_progress = agent.get_in_progress_task()
        assert in_progress == "1.2"

    def test_get_in_progress_task_none(self, temp_project):
        """Test quand aucune tâche n'est in_progress."""
        project_path, feature_dir = temp_project
        config = ProjectConfig()
        agent = DevAgent(project_path, config, feature_dir=feature_dir)

        in_progress = agent.get_in_progress_task()
        assert in_progress is None


class TestDevAgentResume:
    """Tests pour la fonctionnalité de reprise du DevAgent."""

    @pytest.fixture
    def temp_project_with_specs(self):
        """Crée un projet temporaire avec specs et tâches dans feature directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_path = Path(tmpdir)
            feature_dir = project_path / "docs" / "features" / "test-feature"
            feature_dir.mkdir(parents=True)
            (feature_dir / "SPEC.md").write_text("# Specs\nTest spec content")
            (feature_dir / "TASKS.md").write_text("""# Tasks

### Task 1.1: [Migration - Setup]
- **Status**: completed

### Task 1.2: [Model - User]
- **Status**: completed

### Task 1.3: [Controller - Users]
- **Status**: pending

### Task 1.4: [View - Users]
- **Status**: pending
""")
            yield project_path, feature_dir

    def test_build_prompt_without_resume(self, temp_project_with_specs):
        """Test que build_prompt sans resume n'inclut pas l'instruction de reprise."""
        project_path, feature_dir = temp_project_with_specs
        config = ProjectConfig()
        agent = DevAgent(project_path, config, feature_dir=feature_dir)
        prompt = agent.build_prompt()
        assert "MODE REPRISE" not in prompt

    def test_build_prompt_with_resume(self, temp_project_with_specs):
        """Test que build_prompt avec resume inclut l'instruction de reprise."""
        project_path, feature_dir = temp_project_with_specs
        config = ProjectConfig()
        agent = DevAgent(project_path, config, feature_dir=feature_dir)
        prompt = agent.build_prompt(start_from_task="1.3")
        assert "RESUME MODE ACTIVE" in prompt
        assert "task 1.3" in prompt
        assert "Skip all tasks BEFORE task 1.3" in prompt

    def test_get_next_pending_task_after_completed(self, temp_project_with_specs):
        """Test de la recherche de la prochaine tâche après une completed."""
        project_path, feature_dir = temp_project_with_specs
        config = ProjectConfig()
        agent = DevAgent(project_path, config, feature_dir=feature_dir)

        # After 1.2 (completed), next pending is 1.3
        next_task = agent.get_next_pending_task_after("1.2")
        assert next_task == "1.3"

    def test_get_next_pending_task_after_returns_same_if_pending(
        self, temp_project_with_specs
    ):
        """Test que get_next_pending_task_after retourne la même si elle est pending."""
        project_path, feature_dir = temp_project_with_specs
        config = ProjectConfig()
        agent = DevAgent(project_path, config, feature_dir=feature_dir)

        # 1.3 is pending, should return it
        next_task = agent.get_next_pending_task_after("1.3")
        assert next_task == "1.3"

    def test_get_next_pending_task_after_skips_to_next_pending(
        self, temp_project_with_specs
    ):
        """Test que get_next_pending_task_after saute les tâches completed."""
        project_path, feature_dir = temp_project_with_specs
        config = ProjectConfig()
        agent = DevAgent(project_path, config, feature_dir=feature_dir)

        # After 1.1, next pending is 1.3 (1.2 is also completed)
        next_task = agent.get_next_pending_task_after("1.1")
        assert next_task == "1.3"

    def test_get_next_pending_task_after_returns_none_when_all_completed(
        self, temp_project_with_specs
    ):
        """Test que get_next_pending_task_after retourne None si toutes complétées."""
        project_path, feature_dir = temp_project_with_specs
        # Update TASKS.md to have all completed
        (feature_dir / "TASKS.md").write_text("""# Tasks

### Task 1.1: [Migration - Setup]
- **Status**: completed

### Task 1.2: [Model - User]
- **Status**: completed
""")
        config = ProjectConfig()
        agent = DevAgent(project_path, config, feature_dir=feature_dir)

        next_task = agent.get_next_pending_task_after("1.2")
        assert next_task is None

    def test_get_next_pending_task_after_with_in_progress(self, temp_project_with_specs):
        """Test avec une tâche in_progress."""
        project_path, feature_dir = temp_project_with_specs
        (feature_dir / "TASKS.md").write_text("""# Tasks

### Task 1.1: [Migration - Setup]
- **Status**: completed

### Task 1.2: [Model - User]
- **Status**: in_progress

### Task 1.3: [Controller - Users]
- **Status**: pending
""")
        config = ProjectConfig()
        agent = DevAgent(project_path, config, feature_dir=feature_dir)

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


class TestPromptCaching:
    """Tests for prompt template caching."""

    @pytest.fixture
    def temp_project(self):
        """Crée un projet temporaire."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_prompt_cache_hit(self, temp_project):
        """Test that subsequent loads use cache."""
        config = ProjectConfig()

        # Clear cache to start fresh
        BaseAgent.clear_prompt_cache()

        agent1 = ConcreteAgent(temp_project, config)
        agent2 = ConcreteAgent(temp_project, config)

        # First load populates cache
        content1 = agent1.load_prompt_template()

        # Second load should use cache (returns same content)
        content2 = agent2.load_prompt_template()

        assert content1 == content2
        assert len(content1) > 0

    def test_clear_prompt_cache(self, temp_project):
        """Test that clear_prompt_cache empties the cache."""
        config = ProjectConfig()

        # Populate cache
        agent = ConcreteAgent(temp_project, config)
        agent.load_prompt_template()

        # Clear cache
        BaseAgent.clear_prompt_cache()

        # Verify cache is empty
        assert len(BaseAgent._prompt_cache) == 0


class TestPlaceholderReplacement:
    """Tests for placeholder replacement methods."""

    @pytest.fixture
    def temp_project(self):
        """Crée un projet temporaire."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_apply_common_placeholders(self, temp_project):
        """Test that common placeholders are replaced."""
        config = ProjectConfig(
            name="TestProject",
            stack=StackConfig(language="Python", test_command="pytest"),
        )
        agent = ConcreteAgent(temp_project, config)

        template = "Project: {{project_name}}, Lang: {{language}}, Test: {{test_command}}"
        result = agent._apply_common_placeholders(template)

        assert "TestProject" in result
        assert "Python" in result
        assert "pytest" in result
        assert "{{project_name}}" not in result
        assert "{{language}}" not in result
        assert "{{test_command}}" not in result

    def test_apply_placeholders_with_kwargs(self, temp_project):
        """Test that custom placeholders are replaced."""
        config = ProjectConfig(name="TestProject")
        agent = ConcreteAgent(temp_project, config)

        template = "{{project_name}} - {{custom_key}} - {{another}}"
        result = agent._apply_placeholders(
            template,
            custom_key="custom_value",
            another="another_value",
        )

        assert "TestProject" in result
        assert "custom_value" in result
        assert "another_value" in result
        assert "{{custom_key}}" not in result
        assert "{{another}}" not in result

    def test_apply_placeholders_with_none_value(self, temp_project):
        """Test that None values are replaced with empty strings."""
        config = ProjectConfig(name="TestProject")
        agent = ConcreteAgent(temp_project, config)

        template = "{{project_name}}: {{optional}}"
        result = agent._apply_placeholders(template, optional=None)

        assert "TestProject:" in result
        assert "{{optional}}" not in result


class TestTDDInstructions:
    """Tests for TDD instructions placeholder."""

    @pytest.fixture
    def temp_project(self):
        """Creates a temporary project."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_tdd_instructions_disabled_by_default(self, temp_project):
        """Test that TDD instructions are empty when disabled."""
        config = ProjectConfig()
        agent = ConcreteAgent(temp_project, config)

        instructions = agent._get_tdd_instructions()
        assert instructions == ""

    def test_tdd_instructions_enabled(self, temp_project):
        """Test that TDD instructions are returned when enabled."""
        config = ProjectConfig(
            stack=StackConfig(tdd_enabled=True)
        )
        agent = ConcreteAgent(temp_project, config)

        instructions = agent._get_tdd_instructions()
        assert "TDD Workflow" in instructions
        assert "RED" in instructions
        assert "GREEN" in instructions
        assert "REFACTOR" in instructions
        assert "Write Failing Tests First" in instructions

    def test_tdd_placeholder_replacement_disabled(self, temp_project):
        """Test that {{tdd_instructions}} is replaced with empty string when disabled."""
        config = ProjectConfig()
        agent = ConcreteAgent(temp_project, config)

        template = "Before {{tdd_instructions}}After"
        result = agent._apply_common_placeholders(template)

        assert result == "Before After"
        assert "{{tdd_instructions}}" not in result

    def test_tdd_placeholder_replacement_enabled(self, temp_project):
        """Test that {{tdd_instructions}} is replaced with TDD content when enabled."""
        config = ProjectConfig(
            stack=StackConfig(tdd_enabled=True)
        )
        agent = ConcreteAgent(temp_project, config)

        template = "Before\n{{tdd_instructions}}\nAfter"
        result = agent._apply_common_placeholders(template)

        assert "TDD Workflow" in result
        assert "{{tdd_instructions}}" not in result
        assert "Before" in result
        assert "After" in result
