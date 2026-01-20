"""Tests pour le module claude."""

import tempfile
from pathlib import Path

import pytest

from ralph.claude import (
    PID_FILE,
    abort_running_claude,
    check_claude_installed,
    check_gh_installed,
    check_git_installed,
)


class TestPrerequisiteChecks:
    """Tests pour les vérifications de prérequis."""

    def test_check_git_installed(self):
        """Test que git est détecté (normalement installé sur la machine de dev)."""
        # Ce test peut échouer si git n'est pas installé
        result = check_git_installed()
        assert isinstance(result, bool)

    def test_check_gh_installed(self):
        """Test de détection de gh CLI."""
        result = check_gh_installed()
        assert isinstance(result, bool)

    def test_check_claude_installed(self):
        """Test de détection de Claude CLI."""
        result = check_claude_installed()
        assert isinstance(result, bool)


class TestAbortRunningClaude:
    """Tests pour la fonction abort_running_claude."""

    @pytest.fixture
    def temp_project(self):
        """Crée un projet temporaire."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_path = Path(tmpdir)
            (project_path / ".ralph").mkdir()
            yield project_path

    def test_abort_without_pid_file(self, temp_project):
        """Test abort quand il n'y a pas de fichier PID."""
        result = abort_running_claude(temp_project)
        assert result is False

    def test_abort_with_invalid_pid(self, temp_project):
        """Test abort avec un PID invalide."""
        pid_file = temp_project / PID_FILE
        pid_file.write_text("invalid")
        result = abort_running_claude(temp_project)
        assert result is False
        # Le fichier PID devrait être supprimé
        assert not pid_file.exists()

    def test_abort_with_nonexistent_pid(self, temp_project):
        """Test abort avec un PID qui n'existe pas."""
        pid_file = temp_project / PID_FILE
        # Utilise un PID très élevé qui n'existe probablement pas
        pid_file.write_text("999999999")
        result = abort_running_claude(temp_project)
        assert result is False
        # Le fichier PID devrait être supprimé
        assert not pid_file.exists()
