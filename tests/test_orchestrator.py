"""Tests pour l'orchestrateur."""

import tempfile
from pathlib import Path

import pytest

from ralph.orchestrator import Orchestrator, WorkflowError
from ralph.state import Phase, StateManager


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
        (temp_project / ".ralph").mkdir()

        orchestrator = Orchestrator(temp_project)
        orchestrator.abort()

        state_manager = StateManager(temp_project)
        assert state_manager.state.phase == Phase.FAILED
        assert "Avorté" in state_manager.state.error_message

    def test_running_workflow_blocks_new_start(self, temp_project):
        """Test qu'un workflow en cours bloque un nouveau démarrage."""
        (temp_project / "PRD.md").write_text("# Test PRD")
        (temp_project / ".ralph").mkdir()

        # Simule un workflow en cours
        state_manager = StateManager(temp_project)
        state_manager.transition(Phase.SPECIFICATION)

        orchestrator = Orchestrator(temp_project)
        with pytest.raises(WorkflowError, match="déjà en cours"):
            orchestrator._validate_prerequisites()
