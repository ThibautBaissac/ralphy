"""Tests pour le module state."""

import json
import tempfile
import threading
from pathlib import Path

import pytest

from ralphy.state import Phase, StateManager, Status, WorkflowState


class TestWorkflowState:
    """Tests pour WorkflowState."""

    def test_default_state(self):
        """Test de l'état par défaut."""
        state = WorkflowState()
        assert state.phase == Phase.IDLE
        assert state.status == Status.PENDING
        assert state.tasks_completed == 0
        assert state.tasks_total == 0

    def test_from_dict(self):
        """Test de création depuis un dictionnaire."""
        data = {
            "phase": "implementation",
            "status": "running",
            "tasks_completed": 3,
            "tasks_total": 8,
        }
        state = WorkflowState.from_dict(data)
        assert state.phase == Phase.IMPLEMENTATION
        assert state.status == Status.RUNNING
        assert state.tasks_completed == 3
        assert state.tasks_total == 8

    def test_to_dict(self):
        """Test de conversion en dictionnaire."""
        state = WorkflowState(
            phase=Phase.QA,
            status=Status.COMPLETED,
            tasks_completed=5,
            tasks_total=5,
        )
        data = state.to_dict()
        assert data["phase"] == "qa"
        assert data["status"] == "completed"
        assert data["tasks_completed"] == 5


class TestStateManager:
    """Tests pour StateManager."""

    @pytest.fixture
    def temp_project(self):
        """Crée un projet temporaire avec structure de feature."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_path = Path(tmpdir)
            (project_path / ".ralphy").mkdir()
            yield project_path

    @pytest.fixture
    def temp_project_with_feature(self):
        """Crée un projet temporaire avec structure de feature."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_path = Path(tmpdir)
            feature_dir = project_path / "docs" / "features" / "test-feature"
            feature_dir.mkdir(parents=True)
            (feature_dir / ".ralphy").mkdir()
            yield project_path

    def test_load_default_state(self, temp_project):
        """Test du chargement d'un état par défaut (legacy mode)."""
        manager = StateManager(temp_project)
        assert manager.state.phase == Phase.IDLE

    def test_load_default_state_feature(self, temp_project_with_feature):
        """Test du chargement d'un état par défaut (feature mode)."""
        manager = StateManager(temp_project_with_feature, "test-feature")
        assert manager.state.phase == Phase.IDLE

    def test_save_and_load(self, temp_project):
        """Test de sauvegarde et chargement."""
        manager = StateManager(temp_project)
        manager.transition(Phase.SPECIFICATION)
        manager.update_tasks(0, 5)
        manager.save()

        # Nouveau manager charge l'état
        manager2 = StateManager(temp_project)
        assert manager2.state.phase == Phase.SPECIFICATION
        assert manager2.state.tasks_total == 5

    def test_save_and_load_feature(self, temp_project_with_feature):
        """Test de sauvegarde et chargement (feature mode)."""
        manager = StateManager(temp_project_with_feature, "test-feature")
        manager.transition(Phase.SPECIFICATION)
        manager.update_tasks(0, 5)
        manager.save()

        # Nouveau manager charge l'état
        manager2 = StateManager(temp_project_with_feature, "test-feature")
        assert manager2.state.phase == Phase.SPECIFICATION
        assert manager2.state.tasks_total == 5

        # Verify state file is in feature directory
        state_file = temp_project_with_feature / "docs" / "features" / "test-feature" / ".ralphy" / "state.json"
        assert state_file.exists()

    def test_valid_transition(self, temp_project):
        """Test d'une transition valide."""
        manager = StateManager(temp_project)
        assert manager.can_transition(Phase.SPECIFICATION)
        assert manager.transition(Phase.SPECIFICATION)
        assert manager.state.phase == Phase.SPECIFICATION

    def test_invalid_transition(self, temp_project):
        """Test d'une transition invalide."""
        manager = StateManager(temp_project)
        # IDLE ne peut pas transitionner vers COMPLETED ou FAILED directement
        assert not manager.can_transition(Phase.COMPLETED)
        assert not manager.transition(Phase.COMPLETED)
        assert manager.state.phase == Phase.IDLE

    def test_set_failed(self, temp_project):
        """Test du passage en état failed."""
        manager = StateManager(temp_project)
        manager.set_failed("Erreur test")
        assert manager.state.phase == Phase.FAILED
        assert manager.state.status == Status.FAILED
        assert manager.state.error_message == "Erreur test"

    def test_reset(self, temp_project):
        """Test de la réinitialisation."""
        manager = StateManager(temp_project)
        manager.transition(Phase.SPECIFICATION)
        manager.set_failed("Erreur")
        manager.reset()
        assert manager.state.phase == Phase.IDLE
        assert manager.state.error_message is None

    def test_is_running(self, temp_project):
        """Test de la détection d'exécution."""
        manager = StateManager(temp_project)
        assert not manager.is_running()
        manager.transition(Phase.SPECIFICATION)
        assert manager.is_running()

    def test_is_awaiting_validation(self, temp_project):
        """Test de la détection d'attente de validation."""
        manager = StateManager(temp_project)
        manager.transition(Phase.SPECIFICATION)
        manager.transition(Phase.AWAITING_SPEC_VALIDATION)
        assert manager.is_awaiting_validation()

    def test_load_empty_state_file(self, temp_project):
        """Test du chargement d'un fichier state.json vide."""
        state_file = temp_project / ".ralphy" / "state.json"
        state_file.write_text("")

        manager = StateManager(temp_project)
        # Doit retourner l'état par défaut sans erreur
        assert manager.state.phase == Phase.IDLE
        assert manager.state.status == Status.PENDING

    def test_load_corrupted_state_file(self, temp_project):
        """Test du chargement d'un fichier state.json corrompu."""
        state_file = temp_project / ".ralphy" / "state.json"
        state_file.write_text("{invalid json content")

        manager = StateManager(temp_project)
        # Doit retourner l'état par défaut sans erreur
        assert manager.state.phase == Phase.IDLE
        assert manager.state.status == Status.PENDING

    def test_last_completed_phase_default(self, temp_project):
        """Test que last_completed_phase est None par défaut."""
        manager = StateManager(temp_project)
        assert manager.state.last_completed_phase is None

    def test_mark_phase_completed(self, temp_project):
        """Test du marquage d'une phase comme complétée."""
        manager = StateManager(temp_project)
        manager.mark_phase_completed(Phase.SPECIFICATION)
        assert manager.state.last_completed_phase == "specification"

        # Vérifie la persistance
        manager2 = StateManager(temp_project)
        assert manager2.state.last_completed_phase == "specification"

    def test_set_failed_preserves_last_completed_phase(self, temp_project):
        """Test que set_failed préserve last_completed_phase."""
        manager = StateManager(temp_project)
        manager.transition(Phase.SPECIFICATION)
        manager.mark_phase_completed(Phase.SPECIFICATION)
        manager.set_failed("Erreur test")

        assert manager.state.phase == Phase.FAILED
        assert manager.state.last_completed_phase == "specification"

        # Vérifie la persistance
        manager2 = StateManager(temp_project)
        assert manager2.state.last_completed_phase == "specification"

    def test_reset_clears_last_completed_phase(self, temp_project):
        """Test que reset réinitialise last_completed_phase."""
        manager = StateManager(temp_project)
        manager.mark_phase_completed(Phase.IMPLEMENTATION)
        assert manager.state.last_completed_phase == "implementation"

        manager.reset()
        assert manager.state.last_completed_phase is None

    def test_last_completed_phase_from_dict(self):
        """Test de création depuis un dictionnaire avec last_completed_phase."""
        data = {
            "phase": "failed",
            "status": "failed",
            "last_completed_phase": "specification",
        }
        state = WorkflowState.from_dict(data)
        assert state.last_completed_phase == "specification"

    def test_last_completed_phase_to_dict(self):
        """Test de conversion en dictionnaire avec last_completed_phase."""
        state = WorkflowState(
            phase=Phase.FAILED,
            status=Status.FAILED,
            last_completed_phase="implementation",
        )
        data = state.to_dict()
        assert data["last_completed_phase"] == "implementation"

    def test_transition_from_idle_to_any_phase(self, temp_project):
        """Test que IDLE peut transitionner vers toutes les phases (pour reprise)."""
        # Test transitions vers chaque phase active
        phases_to_test = [
            Phase.SPECIFICATION,
            Phase.AWAITING_SPEC_VALIDATION,
            Phase.IMPLEMENTATION,
            Phase.QA,
            Phase.AWAITING_QA_VALIDATION,
            Phase.PR,
        ]

        for target_phase in phases_to_test:
            manager = StateManager(temp_project)
            manager.reset()  # Remet en IDLE
            assert manager.can_transition(target_phase), f"Cannot transition to {target_phase}"
            assert manager.transition(target_phase), f"Transition to {target_phase} failed"
            assert manager.state.phase == target_phase


class TestTaskCheckpoints:
    """Tests pour les checkpoints de tâches."""

    @pytest.fixture
    def temp_project(self):
        """Crée un projet temporaire avec structure de feature."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_path = Path(tmpdir)
            feature_dir = project_path / "docs" / "features" / "test-feature"
            feature_dir.mkdir(parents=True)
            (feature_dir / ".ralphy").mkdir()
            yield project_path, "test-feature"

    def test_checkpoint_task_completed(self, temp_project):
        """Test du checkpoint d'une tâche complétée."""
        project_path, feature_name = temp_project
        manager = StateManager(project_path, feature_name)
        manager.checkpoint_task("1.5", "completed")
        assert manager.state.last_completed_task_id == "1.5"
        assert manager.state.last_in_progress_task_id is None
        assert manager.state.task_checkpoint_time is not None

    def test_checkpoint_task_in_progress(self, temp_project):
        """Test du checkpoint d'une tâche en cours."""
        project_path, feature_name = temp_project
        manager = StateManager(project_path, feature_name)
        manager.checkpoint_task("1.6", "in_progress")
        assert manager.state.last_in_progress_task_id == "1.6"
        assert manager.state.task_checkpoint_time is not None

    def test_completed_clears_in_progress(self, temp_project):
        """Test que marquer completed efface in_progress."""
        project_path, feature_name = temp_project
        manager = StateManager(project_path, feature_name)
        manager.checkpoint_task("1.6", "in_progress")
        assert manager.state.last_in_progress_task_id == "1.6"

        manager.checkpoint_task("1.6", "completed")
        assert manager.state.last_completed_task_id == "1.6"
        assert manager.state.last_in_progress_task_id is None

    def test_get_resume_task_prefers_in_progress(self, temp_project):
        """Test que get_resume_task_id préfère in_progress à completed."""
        project_path, feature_name = temp_project
        manager = StateManager(project_path, feature_name)
        manager.checkpoint_task("1.5", "completed")
        manager.checkpoint_task("1.6", "in_progress")

        # in_progress has priority
        assert manager.get_resume_task_id() == "1.6"

    def test_get_resume_task_returns_completed_when_no_in_progress(self, temp_project):
        """Test que get_resume_task_id retourne completed si pas de in_progress."""
        project_path, feature_name = temp_project
        manager = StateManager(project_path, feature_name)
        manager.checkpoint_task("1.5", "completed")

        assert manager.get_resume_task_id() == "1.5"

    def test_get_resume_task_returns_none_when_empty(self, temp_project):
        """Test que get_resume_task_id retourne None si pas de checkpoint."""
        project_path, feature_name = temp_project
        manager = StateManager(project_path, feature_name)
        assert manager.get_resume_task_id() is None

    def test_clear_task_checkpoints(self, temp_project):
        """Test de l'effacement des checkpoints."""
        project_path, feature_name = temp_project
        manager = StateManager(project_path, feature_name)
        manager.checkpoint_task("1.5", "completed")
        manager.checkpoint_task("1.6", "in_progress")

        manager.clear_task_checkpoints()

        assert manager.state.last_completed_task_id is None
        assert manager.state.last_in_progress_task_id is None
        assert manager.state.task_checkpoint_time is None

    def test_checkpoint_persistence(self, temp_project):
        """Test de la persistance des checkpoints."""
        project_path, feature_name = temp_project
        manager1 = StateManager(project_path, feature_name)
        manager1.checkpoint_task("2.3", "completed")

        # Create new manager - should load persisted state
        manager2 = StateManager(project_path, feature_name)
        assert manager2.state.last_completed_task_id == "2.3"

    def test_checkpoint_fields_in_from_dict(self):
        """Test de la désérialisation des champs de checkpoint."""
        data = {
            "phase": "implementation",
            "status": "running",
            "last_completed_task_id": "1.5",
            "last_in_progress_task_id": "1.6",
            "task_checkpoint_time": "2024-01-15T10:30:00",
        }
        state = WorkflowState.from_dict(data)
        assert state.last_completed_task_id == "1.5"
        assert state.last_in_progress_task_id == "1.6"
        assert state.task_checkpoint_time == "2024-01-15T10:30:00"

    def test_checkpoint_fields_in_to_dict(self):
        """Test de la sérialisation des champs de checkpoint."""
        state = WorkflowState(
            phase=Phase.IMPLEMENTATION,
            status=Status.RUNNING,
            last_completed_task_id="2.1",
            last_in_progress_task_id="2.2",
            task_checkpoint_time="2024-01-15T11:00:00",
        )
        data = state.to_dict()
        assert data["last_completed_task_id"] == "2.1"
        assert data["last_in_progress_task_id"] == "2.2"
        assert data["task_checkpoint_time"] == "2024-01-15T11:00:00"

    def test_reset_clears_task_checkpoints(self, temp_project):
        """Test que reset efface les checkpoints de tâche."""
        project_path, feature_name = temp_project
        manager = StateManager(project_path, feature_name)
        manager.checkpoint_task("1.5", "completed")
        manager.checkpoint_task("1.6", "in_progress")

        manager.reset()

        assert manager.state.last_completed_task_id is None
        assert manager.state.last_in_progress_task_id is None


class TestStateManagerThreadSafety:
    """Tests for StateManager thread safety."""

    @pytest.fixture
    def temp_project(self):
        """Crée un projet temporaire."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_path = Path(tmpdir)
            (project_path / ".ralphy").mkdir()
            yield project_path

    def test_concurrent_state_access(self, temp_project):
        """Multiple threads accessing state property simultaneously.

        All threads should see the same state object (identity check).
        """
        manager = StateManager(temp_project)
        results = []
        errors = []

        def access_state():
            try:
                for _ in range(100):
                    state = manager.state
                    results.append(id(state))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=access_state) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Errors occurred: {errors}"
        # All accesses should return the same state object
        assert len(set(results)) == 1, "State object identity varies across threads"

    def test_concurrent_save(self, temp_project):
        """Multiple threads calling save() simultaneously.

        No corruption should occur - state file should be valid JSON.
        """
        manager = StateManager(temp_project)
        manager.transition(Phase.SPECIFICATION)
        errors = []

        def save_state(thread_id: int):
            try:
                for i in range(50):
                    manager.state.tasks_completed = thread_id * 100 + i
                    manager.save()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=save_state, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Errors occurred: {errors}"

        # Verify state file is valid JSON and not corrupted
        with open(manager.state_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert "phase" in data
        assert "status" in data

    def test_concurrent_transition(self, temp_project):
        """Multiple threads attempting transitions simultaneously.

        State must remain consistent - only valid transitions should occur.
        """
        manager = StateManager(temp_project)
        successful_transitions = []
        errors = []
        lock = threading.Lock()

        def attempt_transition():
            try:
                # Try to transition from IDLE to SPECIFICATION
                result = manager.transition(Phase.SPECIFICATION)
                with lock:
                    successful_transitions.append(result)
            except Exception as e:
                with lock:
                    errors.append(e)

        # All threads try to transition at once
        threads = [threading.Thread(target=attempt_transition) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Errors occurred: {errors}"
        # State should be in SPECIFICATION
        assert manager.state.phase == Phase.SPECIFICATION
        # At least one transition should have succeeded
        assert any(successful_transitions)


class TestFeatureNameValidation:
    """Tests for feature name validation."""

    @pytest.fixture
    def temp_project(self):
        """Crée un projet temporaire."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_path = Path(tmpdir)
            (project_path / ".ralphy").mkdir()
            yield project_path

    def test_valid_feature_names_accepted(self, temp_project):
        """Test that valid feature names are accepted."""
        valid_names = [
            "my-feature",
            "feature123",
            "Feature_Name",
            "a",
            "A1-b2_c3",
        ]
        for name in valid_names:
            # Create the feature directory structure
            feature_dir = temp_project / "docs" / "features" / name / ".ralphy"
            feature_dir.mkdir(parents=True, exist_ok=True)

            # Should not raise
            manager = StateManager(temp_project, name)
            assert manager.feature_name == name

    def test_path_traversal_rejected(self, temp_project):
        """Test that path traversal attempts are rejected."""
        invalid_names = [
            "../etc/passwd",
            "feature/../other",
            "feature/subdir",
            "feature\\subdir",
            "..feature",
        ]
        for name in invalid_names:
            with pytest.raises(ValueError, match="Invalid feature name"):
                StateManager(temp_project, name)

    def test_invalid_format_rejected(self, temp_project):
        """Test that invalid format feature names are rejected."""
        invalid_names = [
            "-starts-with-dash",
            "_starts_with_underscore",
            "has space",
            "has.dot",
            "",
        ]
        for name in invalid_names:
            if name:  # Empty string is handled differently
                with pytest.raises(ValueError, match="Invalid feature name"):
                    StateManager(temp_project, name)


class TestSymlinkProtection:
    """Tests for symlink protection."""

    @pytest.fixture
    def temp_project(self):
        """Crée un projet temporaire avec structure de feature."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_path = Path(tmpdir)
            (project_path / ".ralphy").mkdir()
            yield project_path

    def test_symlink_ralphy_dir_outside_project_rejected(self, temp_project):
        """Test that .ralphy symlink pointing outside project is rejected."""
        import os

        # Create external target
        with tempfile.TemporaryDirectory() as external_dir:
            external_path = Path(external_dir)

            # Create symlinked .ralphy in a feature dir
            feature_dir = temp_project / "docs" / "features" / "test-feature"
            feature_dir.mkdir(parents=True)

            # Create symlink pointing outside project
            symlink_path = feature_dir / ".ralphy"
            os.symlink(external_path, symlink_path)

            with pytest.raises(ValueError, match="symlink pointing outside project"):
                StateManager(temp_project, "test-feature")

    def test_symlink_within_project_accepted(self, temp_project):
        """Test that symlinks within project are accepted."""
        import os

        # Create target within project
        actual_ralphy = temp_project / "actual_ralphy"
        actual_ralphy.mkdir()

        # Create feature dir
        feature_dir = temp_project / "docs" / "features" / "test-feature"
        feature_dir.mkdir(parents=True)

        # Create symlink within project
        symlink_path = feature_dir / ".ralphy"
        os.symlink(actual_ralphy, symlink_path)

        # Should not raise
        manager = StateManager(temp_project, "test-feature")
        assert manager.feature_name == "test-feature"

    def test_non_symlink_path_accepted(self, temp_project):
        """Test that regular directories are accepted."""
        feature_dir = temp_project / "docs" / "features" / "test-feature" / ".ralphy"
        feature_dir.mkdir(parents=True)

        # Should not raise
        manager = StateManager(temp_project, "test-feature")
        assert manager.feature_name == "test-feature"
