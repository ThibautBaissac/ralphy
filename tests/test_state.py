"""Tests pour le module state."""

import json
import tempfile
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
        """Crée un projet temporaire."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_path = Path(tmpdir)
            (project_path / ".ralphy").mkdir()
            yield project_path

    def test_load_default_state(self, temp_project):
        """Test du chargement d'un état par défaut."""
        manager = StateManager(temp_project)
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
