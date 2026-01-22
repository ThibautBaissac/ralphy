"""Tests for the orchestrator."""

import tempfile
from pathlib import Path

import pytest

from ralphy.orchestrator import Orchestrator, WorkflowError
from ralphy.state import Phase, StateManager


FEATURE_NAME = "test-feature"


class TestOrchestrator:
    """Tests for Orchestrator."""

    @pytest.fixture
    def temp_project(self):
        """Creates a temporary project with feature structure."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_path = Path(tmpdir)
            # Create feature directory structure
            feature_dir = project_path / "docs" / "features" / FEATURE_NAME
            feature_dir.mkdir(parents=True)
            yield project_path

    def test_missing_prd_raises_error(self, temp_project):
        """Test that missing PRD.md raises an error."""
        orchestrator = Orchestrator(temp_project, feature_name=FEATURE_NAME)
        with pytest.raises(WorkflowError, match="PRD.md non trouvé"):
            orchestrator._validate_prerequisites()

    def test_validates_with_prd(self, temp_project):
        """Test que la validation passe avec PRD.md."""
        feature_dir = temp_project / "docs" / "features" / FEATURE_NAME
        (feature_dir / "PRD.md").write_text("# Test PRD")
        orchestrator = Orchestrator(temp_project, feature_name=FEATURE_NAME)
        # Ne doit pas lever d'exception
        orchestrator._validate_prerequisites()

    def test_abort_sets_failed(self, temp_project):
        """Test que abort passe en état failed."""
        feature_dir = temp_project / "docs" / "features" / FEATURE_NAME
        (feature_dir / "PRD.md").write_text("# Test PRD")
        (feature_dir / ".ralphy").mkdir()

        orchestrator = Orchestrator(temp_project, feature_name=FEATURE_NAME)
        orchestrator.abort()

        state_manager = StateManager(temp_project, FEATURE_NAME)
        assert state_manager.state.phase == Phase.FAILED
        assert "Avorté" in state_manager.state.error_message

    def test_running_workflow_blocks_new_start(self, temp_project):
        """Test qu'un workflow en cours bloque un nouveau démarrage."""
        feature_dir = temp_project / "docs" / "features" / FEATURE_NAME
        (feature_dir / "PRD.md").write_text("# Test PRD")
        (feature_dir / ".ralphy").mkdir()

        # Simule un workflow en cours
        state_manager = StateManager(temp_project, FEATURE_NAME)
        state_manager.transition(Phase.SPECIFICATION)

        orchestrator = Orchestrator(temp_project, feature_name=FEATURE_NAME)
        with pytest.raises(WorkflowError, match="déjà en cours"):
            orchestrator._validate_prerequisites()


class TestResumeLogic:
    """Tests pour la logique de reprise du workflow."""

    @pytest.fixture
    def temp_project_with_specs(self):
        """Crée un projet temporaire avec des artéfacts de spec valides."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            project_path = Path(tmpdir)
            feature_dir = project_path / "docs" / "features" / FEATURE_NAME
            feature_dir.mkdir(parents=True)
            (feature_dir / "PRD.md").write_text("# Test PRD\n" + "x" * 500)
            (feature_dir / ".ralphy").mkdir()
            # Créer des fichiers de spec suffisamment grands
            (feature_dir / "SPEC.md").write_text("# Spec\n" + "x" * 1500)
            (feature_dir / "TASKS.md").write_text("# Tasks\n" + "x" * 800)
            yield project_path

    @pytest.fixture
    def temp_project_with_qa(self, temp_project_with_specs):
        """Crée un projet avec artéfacts de spec et QA."""
        feature_dir = temp_project_with_specs / "docs" / "features" / FEATURE_NAME
        (feature_dir / "QA_REPORT.md").write_text(
            "# QA Report\n" + "x" * 800
        )
        return temp_project_with_specs

    def test_spec_artifacts_valid_with_valid_files(self, temp_project_with_specs):
        """Test que _spec_artifacts_valid retourne True avec fichiers valides."""
        orchestrator = Orchestrator(temp_project_with_specs, feature_name=FEATURE_NAME)
        assert orchestrator._spec_artifacts_valid() is True

    def test_spec_artifacts_valid_with_missing_files(self, temp_project_with_specs):
        """Test que _spec_artifacts_valid retourne False si fichiers manquants."""
        feature_dir = temp_project_with_specs / "docs" / "features" / FEATURE_NAME
        (feature_dir / "SPEC.md").unlink()
        orchestrator = Orchestrator(temp_project_with_specs, feature_name=FEATURE_NAME)
        assert orchestrator._spec_artifacts_valid() is False

    def test_spec_artifacts_valid_with_small_files(self, temp_project_with_specs):
        """Test que _spec_artifacts_valid retourne False si fichiers trop petits."""
        feature_dir = temp_project_with_specs / "docs" / "features" / FEATURE_NAME
        (feature_dir / "SPEC.md").write_text("small")
        orchestrator = Orchestrator(temp_project_with_specs, feature_name=FEATURE_NAME)
        assert orchestrator._spec_artifacts_valid() is False

    def test_qa_artifacts_valid_with_valid_file(self, temp_project_with_qa):
        """Test que _qa_artifacts_valid retourne True avec fichier valide."""
        orchestrator = Orchestrator(temp_project_with_qa, feature_name=FEATURE_NAME)
        assert orchestrator._qa_artifacts_valid() is True

    def test_qa_artifacts_valid_with_missing_file(self, temp_project_with_specs):
        """Test que _qa_artifacts_valid retourne False si fichier manquant."""
        orchestrator = Orchestrator(temp_project_with_specs, feature_name=FEATURE_NAME)
        assert orchestrator._qa_artifacts_valid() is False

    def test_determine_resume_phase_without_last_completed(self, temp_project_with_specs):
        """Test que _determine_resume_phase retourne None sans last_completed_phase."""
        orchestrator = Orchestrator(temp_project_with_specs, feature_name=FEATURE_NAME)
        assert orchestrator._determine_resume_phase() is None

    def test_determine_resume_phase_after_specification(self, temp_project_with_specs):
        """Test de reprise après SPECIFICATION complétée."""
        state_manager = StateManager(temp_project_with_specs, FEATURE_NAME)
        state_manager.mark_phase_completed(Phase.SPECIFICATION)
        state_manager.set_failed("Test interruption")

        orchestrator = Orchestrator(temp_project_with_specs, feature_name=FEATURE_NAME)
        resume_phase = orchestrator._determine_resume_phase()
        assert resume_phase == Phase.AWAITING_SPEC_VALIDATION

    def test_determine_resume_phase_after_spec_validation(self, temp_project_with_specs):
        """Test de reprise après validation SPEC complétée."""
        state_manager = StateManager(temp_project_with_specs, FEATURE_NAME)
        state_manager.mark_phase_completed(Phase.AWAITING_SPEC_VALIDATION)
        state_manager.set_failed("Test interruption")

        orchestrator = Orchestrator(temp_project_with_specs, feature_name=FEATURE_NAME)
        resume_phase = orchestrator._determine_resume_phase()
        assert resume_phase == Phase.IMPLEMENTATION

    def test_determine_resume_phase_after_implementation(self, temp_project_with_specs):
        """Test de reprise après IMPLEMENTATION complétée."""
        state_manager = StateManager(temp_project_with_specs, FEATURE_NAME)
        state_manager.mark_phase_completed(Phase.IMPLEMENTATION)
        state_manager.set_failed("Test interruption")

        orchestrator = Orchestrator(temp_project_with_specs, feature_name=FEATURE_NAME)
        resume_phase = orchestrator._determine_resume_phase()
        assert resume_phase == Phase.QA

    def test_determine_resume_phase_after_qa(self, temp_project_with_qa):
        """Test de reprise après QA complétée."""
        state_manager = StateManager(temp_project_with_qa, FEATURE_NAME)
        state_manager.mark_phase_completed(Phase.QA)
        state_manager.set_failed("Test interruption")

        orchestrator = Orchestrator(temp_project_with_qa, feature_name=FEATURE_NAME)
        resume_phase = orchestrator._determine_resume_phase()
        assert resume_phase == Phase.AWAITING_QA_VALIDATION

    def test_determine_resume_phase_with_missing_artifacts(self, temp_project_with_specs):
        """Test que _determine_resume_phase retourne None si artéfacts manquants."""
        state_manager = StateManager(temp_project_with_specs, FEATURE_NAME)
        state_manager.mark_phase_completed(Phase.SPECIFICATION)
        state_manager.set_failed("Test interruption")

        # Supprime SPEC.md pour invalider les artéfacts
        feature_dir = temp_project_with_specs / "docs" / "features" / FEATURE_NAME
        (feature_dir / "SPEC.md").unlink()

        orchestrator = Orchestrator(temp_project_with_specs, feature_name=FEATURE_NAME)
        resume_phase = orchestrator._determine_resume_phase()
        assert resume_phase is None

    def test_should_skip_phase_without_resume(self, temp_project_with_specs):
        """Test que _should_skip_phase retourne False sans phase de reprise."""
        orchestrator = Orchestrator(temp_project_with_specs, feature_name=FEATURE_NAME)
        assert orchestrator._should_skip_phase(Phase.SPECIFICATION, None) is False

    def test_should_skip_phase_before_resume_point(self, temp_project_with_specs):
        """Test que les phases avant le point de reprise sont sautées."""
        orchestrator = Orchestrator(temp_project_with_specs, feature_name=FEATURE_NAME)
        # Si on reprend à IMPLEMENTATION, on doit sauter SPECIFICATION et AWAITING_SPEC_VALIDATION
        assert orchestrator._should_skip_phase(Phase.SPECIFICATION, Phase.IMPLEMENTATION) is True
        assert orchestrator._should_skip_phase(Phase.AWAITING_SPEC_VALIDATION, Phase.IMPLEMENTATION) is True
        assert orchestrator._should_skip_phase(Phase.IMPLEMENTATION, Phase.IMPLEMENTATION) is False

    def test_should_skip_phase_at_and_after_resume_point(self, temp_project_with_specs):
        """Test que les phases au point de reprise et après ne sont pas sautées."""
        orchestrator = Orchestrator(temp_project_with_specs, feature_name=FEATURE_NAME)
        # Si on reprend à QA, QA et phases suivantes ne sont pas sautées
        assert orchestrator._should_skip_phase(Phase.QA, Phase.QA) is False
        assert orchestrator._should_skip_phase(Phase.AWAITING_QA_VALIDATION, Phase.QA) is False
        assert orchestrator._should_skip_phase(Phase.PR, Phase.QA) is False


class TestTaskLevelResume:
    """Tests pour la reprise au niveau des tâches."""

    @pytest.fixture
    def temp_project_with_tasks(self):
        """Crée un projet avec specs et tâches partiellement complétées."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            project_path = Path(tmpdir)
            feature_dir = project_path / "docs" / "features" / FEATURE_NAME
            feature_dir.mkdir(parents=True)
            (feature_dir / "PRD.md").write_text("# Test PRD\n" + "x" * 500)
            (feature_dir / ".ralphy").mkdir()
            (feature_dir / "SPEC.md").write_text("# Spec\n" + "x" * 1500)
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
            yield project_path

    def test_get_implementation_resume_task_with_completed_checkpoint(
        self, temp_project_with_tasks
    ):
        """Test de reprise depuis un checkpoint de tâche complétée."""
        state_manager = StateManager(temp_project_with_tasks, FEATURE_NAME)
        state_manager.checkpoint_task("1.2", "completed")

        orchestrator = Orchestrator(temp_project_with_tasks, feature_name=FEATURE_NAME)
        resume_task = orchestrator._get_implementation_resume_task()

        # Should resume from 1.3 (first pending after 1.2)
        assert resume_task == "1.3"

    def test_get_implementation_resume_task_with_in_progress_checkpoint(
        self, temp_project_with_tasks
    ):
        """Test de reprise depuis un checkpoint de tâche in_progress."""
        # Update TASKS.md to have 1.3 as in_progress
        feature_dir = temp_project_with_tasks / "docs" / "features" / FEATURE_NAME
        (feature_dir / "TASKS.md").write_text("""# Tasks

### Task 1.1: [Migration - Setup]
- **Status**: completed

### Task 1.2: [Model - User]
- **Status**: completed

### Task 1.3: [Controller - Users]
- **Status**: in_progress

### Task 1.4: [View - Users]
- **Status**: pending
""")
        state_manager = StateManager(temp_project_with_tasks, FEATURE_NAME)
        state_manager.checkpoint_task("1.2", "completed")
        state_manager.checkpoint_task("1.3", "in_progress")

        orchestrator = Orchestrator(temp_project_with_tasks, feature_name=FEATURE_NAME)
        resume_task = orchestrator._get_implementation_resume_task()

        # Should resume from 1.3 (the in_progress task)
        assert resume_task == "1.3"

    def test_get_implementation_resume_task_returns_none_without_checkpoint(
        self, temp_project_with_tasks
    ):
        """Test que _get_implementation_resume_task retourne None sans checkpoint."""
        orchestrator = Orchestrator(temp_project_with_tasks, feature_name=FEATURE_NAME)
        resume_task = orchestrator._get_implementation_resume_task()

        assert resume_task is None

    def test_get_implementation_resume_task_returns_none_when_all_completed(
        self, temp_project_with_tasks
    ):
        """Test que _get_implementation_resume_task retourne None si toutes complétées."""
        # Update TASKS.md to have all completed
        feature_dir = temp_project_with_tasks / "docs" / "features" / FEATURE_NAME
        (feature_dir / "TASKS.md").write_text("""# Tasks

### Task 1.1: [Migration - Setup]
- **Status**: completed

### Task 1.2: [Model - User]
- **Status**: completed
""")
        state_manager = StateManager(temp_project_with_tasks, FEATURE_NAME)
        state_manager.checkpoint_task("1.2", "completed")

        orchestrator = Orchestrator(temp_project_with_tasks, feature_name=FEATURE_NAME)
        resume_task = orchestrator._get_implementation_resume_task()

        # All tasks completed, no resume needed
        assert resume_task is None
