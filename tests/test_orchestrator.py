"""Tests pour l'orchestrateur."""

import tempfile
from pathlib import Path

import pytest

from ralphy.orchestrator import Orchestrator, WorkflowError
from ralphy.state import Phase, StateManager


class TestOrchestrator:
    """Tests pour Orchestrator."""

    @pytest.fixture
    def temp_project(self):
        """Crée un projet temporaire."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_path = Path(tmpdir)
            yield project_path

    def test_missing_prd_raises_error(self, temp_project):
        """Test que l'absence de PRD.md lève une erreur."""
        orchestrator = Orchestrator(temp_project)
        with pytest.raises(WorkflowError, match="PRD.md non trouvé"):
            orchestrator._validate_prerequisites()

    def test_validates_with_prd(self, temp_project):
        """Test que la validation passe avec PRD.md."""
        (temp_project / "PRD.md").write_text("# Test PRD")
        orchestrator = Orchestrator(temp_project)
        # Ne doit pas lever d'exception
        orchestrator._validate_prerequisites()

    def test_abort_sets_failed(self, temp_project):
        """Test que abort passe en état failed."""
        (temp_project / "PRD.md").write_text("# Test PRD")
        (temp_project / ".ralphy").mkdir()

        orchestrator = Orchestrator(temp_project)
        orchestrator.abort()

        state_manager = StateManager(temp_project)
        assert state_manager.state.phase == Phase.FAILED
        assert "Avorté" in state_manager.state.error_message

    def test_running_workflow_blocks_new_start(self, temp_project):
        """Test qu'un workflow en cours bloque un nouveau démarrage."""
        (temp_project / "PRD.md").write_text("# Test PRD")
        (temp_project / ".ralphy").mkdir()

        # Simule un workflow en cours
        state_manager = StateManager(temp_project)
        state_manager.transition(Phase.SPECIFICATION)

        orchestrator = Orchestrator(temp_project)
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
            (project_path / "PRD.md").write_text("# Test PRD\n" + "x" * 500)
            (project_path / ".ralphy").mkdir()
            (project_path / "specs").mkdir()
            # Créer des fichiers de spec suffisamment grands
            (project_path / "specs" / "SPEC.md").write_text("# Spec\n" + "x" * 1500)
            (project_path / "specs" / "TASKS.md").write_text("# Tasks\n" + "x" * 800)
            yield project_path

    @pytest.fixture
    def temp_project_with_qa(self, temp_project_with_specs):
        """Crée un projet avec artéfacts de spec et QA."""
        (temp_project_with_specs / "specs" / "QA_REPORT.md").write_text(
            "# QA Report\n" + "x" * 800
        )
        return temp_project_with_specs

    def test_spec_artifacts_valid_with_valid_files(self, temp_project_with_specs):
        """Test que _spec_artifacts_valid retourne True avec fichiers valides."""
        orchestrator = Orchestrator(temp_project_with_specs)
        assert orchestrator._spec_artifacts_valid() is True

    def test_spec_artifacts_valid_with_missing_files(self, temp_project_with_specs):
        """Test que _spec_artifacts_valid retourne False si fichiers manquants."""
        (temp_project_with_specs / "specs" / "SPEC.md").unlink()
        orchestrator = Orchestrator(temp_project_with_specs)
        assert orchestrator._spec_artifacts_valid() is False

    def test_spec_artifacts_valid_with_small_files(self, temp_project_with_specs):
        """Test que _spec_artifacts_valid retourne False si fichiers trop petits."""
        (temp_project_with_specs / "specs" / "SPEC.md").write_text("small")
        orchestrator = Orchestrator(temp_project_with_specs)
        assert orchestrator._spec_artifacts_valid() is False

    def test_qa_artifacts_valid_with_valid_file(self, temp_project_with_qa):
        """Test que _qa_artifacts_valid retourne True avec fichier valide."""
        orchestrator = Orchestrator(temp_project_with_qa)
        assert orchestrator._qa_artifacts_valid() is True

    def test_qa_artifacts_valid_with_missing_file(self, temp_project_with_specs):
        """Test que _qa_artifacts_valid retourne False si fichier manquant."""
        orchestrator = Orchestrator(temp_project_with_specs)
        assert orchestrator._qa_artifacts_valid() is False

    def test_determine_resume_phase_without_last_completed(self, temp_project_with_specs):
        """Test que _determine_resume_phase retourne None sans last_completed_phase."""
        orchestrator = Orchestrator(temp_project_with_specs)
        assert orchestrator._determine_resume_phase() is None

    def test_determine_resume_phase_after_specification(self, temp_project_with_specs):
        """Test de reprise après SPECIFICATION complétée."""
        state_manager = StateManager(temp_project_with_specs)
        state_manager.mark_phase_completed(Phase.SPECIFICATION)
        state_manager.set_failed("Test interruption")

        orchestrator = Orchestrator(temp_project_with_specs)
        resume_phase = orchestrator._determine_resume_phase()
        assert resume_phase == Phase.AWAITING_SPEC_VALIDATION

    def test_determine_resume_phase_after_spec_validation(self, temp_project_with_specs):
        """Test de reprise après validation SPEC complétée."""
        state_manager = StateManager(temp_project_with_specs)
        state_manager.mark_phase_completed(Phase.AWAITING_SPEC_VALIDATION)
        state_manager.set_failed("Test interruption")

        orchestrator = Orchestrator(temp_project_with_specs)
        resume_phase = orchestrator._determine_resume_phase()
        assert resume_phase == Phase.IMPLEMENTATION

    def test_determine_resume_phase_after_implementation(self, temp_project_with_specs):
        """Test de reprise après IMPLEMENTATION complétée."""
        state_manager = StateManager(temp_project_with_specs)
        state_manager.mark_phase_completed(Phase.IMPLEMENTATION)
        state_manager.set_failed("Test interruption")

        orchestrator = Orchestrator(temp_project_with_specs)
        resume_phase = orchestrator._determine_resume_phase()
        assert resume_phase == Phase.QA

    def test_determine_resume_phase_after_qa(self, temp_project_with_qa):
        """Test de reprise après QA complétée."""
        state_manager = StateManager(temp_project_with_qa)
        state_manager.mark_phase_completed(Phase.QA)
        state_manager.set_failed("Test interruption")

        orchestrator = Orchestrator(temp_project_with_qa)
        resume_phase = orchestrator._determine_resume_phase()
        assert resume_phase == Phase.AWAITING_QA_VALIDATION

    def test_determine_resume_phase_with_missing_artifacts(self, temp_project_with_specs):
        """Test que _determine_resume_phase retourne None si artéfacts manquants."""
        state_manager = StateManager(temp_project_with_specs)
        state_manager.mark_phase_completed(Phase.SPECIFICATION)
        state_manager.set_failed("Test interruption")

        # Supprime SPEC.md pour invalider les artéfacts
        (temp_project_with_specs / "specs" / "SPEC.md").unlink()

        orchestrator = Orchestrator(temp_project_with_specs)
        resume_phase = orchestrator._determine_resume_phase()
        assert resume_phase is None

    def test_should_skip_phase_without_resume(self, temp_project_with_specs):
        """Test que _should_skip_phase retourne False sans phase de reprise."""
        orchestrator = Orchestrator(temp_project_with_specs)
        assert orchestrator._should_skip_phase(Phase.SPECIFICATION, None) is False

    def test_should_skip_phase_before_resume_point(self, temp_project_with_specs):
        """Test que les phases avant le point de reprise sont sautées."""
        orchestrator = Orchestrator(temp_project_with_specs)
        # Si on reprend à IMPLEMENTATION, on doit sauter SPECIFICATION et AWAITING_SPEC_VALIDATION
        assert orchestrator._should_skip_phase(Phase.SPECIFICATION, Phase.IMPLEMENTATION) is True
        assert orchestrator._should_skip_phase(Phase.AWAITING_SPEC_VALIDATION, Phase.IMPLEMENTATION) is True
        assert orchestrator._should_skip_phase(Phase.IMPLEMENTATION, Phase.IMPLEMENTATION) is False

    def test_should_skip_phase_at_and_after_resume_point(self, temp_project_with_specs):
        """Test que les phases au point de reprise et après ne sont pas sautées."""
        orchestrator = Orchestrator(temp_project_with_specs)
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
            (project_path / "PRD.md").write_text("# Test PRD\n" + "x" * 500)
            (project_path / ".ralphy").mkdir()
            (project_path / "specs").mkdir()
            (project_path / "specs" / "SPEC.md").write_text("# Spec\n" + "x" * 1500)
            (project_path / "specs" / "TASKS.md").write_text("""# Tâches

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

    def test_get_implementation_resume_task_with_completed_checkpoint(
        self, temp_project_with_tasks
    ):
        """Test de reprise depuis un checkpoint de tâche complétée."""
        state_manager = StateManager(temp_project_with_tasks)
        state_manager.checkpoint_task("1.2", "completed")

        orchestrator = Orchestrator(temp_project_with_tasks)
        resume_task = orchestrator._get_implementation_resume_task()

        # Should resume from 1.3 (first pending after 1.2)
        assert resume_task == "1.3"

    def test_get_implementation_resume_task_with_in_progress_checkpoint(
        self, temp_project_with_tasks
    ):
        """Test de reprise depuis un checkpoint de tâche in_progress."""
        # Update TASKS.md to have 1.3 as in_progress
        (temp_project_with_tasks / "specs" / "TASKS.md").write_text("""# Tâches

### Tâche 1.1: [Migration - Setup]
- **Statut**: completed

### Tâche 1.2: [Model - User]
- **Statut**: completed

### Tâche 1.3: [Controller - Users]
- **Statut**: in_progress

### Tâche 1.4: [View - Users]
- **Statut**: pending
""")
        state_manager = StateManager(temp_project_with_tasks)
        state_manager.checkpoint_task("1.2", "completed")
        state_manager.checkpoint_task("1.3", "in_progress")

        orchestrator = Orchestrator(temp_project_with_tasks)
        resume_task = orchestrator._get_implementation_resume_task()

        # Should resume from 1.3 (the in_progress task)
        assert resume_task == "1.3"

    def test_get_implementation_resume_task_returns_none_without_checkpoint(
        self, temp_project_with_tasks
    ):
        """Test que _get_implementation_resume_task retourne None sans checkpoint."""
        orchestrator = Orchestrator(temp_project_with_tasks)
        resume_task = orchestrator._get_implementation_resume_task()

        assert resume_task is None

    def test_get_implementation_resume_task_returns_none_when_all_completed(
        self, temp_project_with_tasks
    ):
        """Test que _get_implementation_resume_task retourne None si toutes complétées."""
        # Update TASKS.md to have all completed
        (temp_project_with_tasks / "specs" / "TASKS.md").write_text("""# Tâches

### Tâche 1.1: [Migration - Setup]
- **Statut**: completed

### Tâche 1.2: [Model - User]
- **Statut**: completed
""")
        state_manager = StateManager(temp_project_with_tasks)
        state_manager.checkpoint_task("1.2", "completed")

        orchestrator = Orchestrator(temp_project_with_tasks)
        resume_task = orchestrator._get_implementation_resume_task()

        # All tasks completed, no resume needed
        assert resume_task is None
