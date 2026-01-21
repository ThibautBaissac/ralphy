"""Tests pour le module claude."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ralphy.claude import (
    PID_FILE,
    ClaudeRunner,
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
            (project_path / ".ralphy").mkdir()
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


class TestClaudeRunnerModelFlag:
    """Tests pour la construction du flag --model dans ClaudeRunner."""

    @pytest.fixture
    def temp_project(self):
        """Crée un projet temporaire."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_path = Path(tmpdir)
            (project_path / ".ralphy").mkdir()
            yield project_path

    def test_runner_stores_model_parameter(self, temp_project):
        """Test que ClaudeRunner stocke le paramètre model."""
        runner = ClaudeRunner(working_dir=temp_project, model="opus")
        assert runner.model == "opus"

    def test_runner_model_defaults_to_none(self, temp_project):
        """Test que ClaudeRunner a model=None par défaut."""
        runner = ClaudeRunner(working_dir=temp_project)
        assert runner.model is None

    def test_run_includes_model_flag_when_specified(self, temp_project):
        """Test que run() inclut --model dans la commande quand spécifié."""
        with patch("ralphy.claude.subprocess.Popen") as mock_popen:
            mock_process = MagicMock()
            mock_process.stdout = MagicMock()
            mock_process.stdout.fileno.return_value = 0
            mock_process.stdout.read.return_value = ""
            mock_process.poll.return_value = 0
            mock_process.wait.return_value = 0
            mock_process.returncode = 0
            mock_process.pid = 12345
            mock_popen.return_value = mock_process

            runner = ClaudeRunner(working_dir=temp_project, model="opus")
            runner.run("test prompt")

            # Verify Popen was called with the model flag
            call_args = mock_popen.call_args
            cmd = call_args[0][0]  # First positional arg is the command list

            assert "--model" in cmd
            model_idx = cmd.index("--model")
            assert cmd[model_idx + 1] == "opus"

    def test_run_omits_model_flag_when_none(self, temp_project):
        """Test que run() n'inclut pas --model quand model=None."""
        with patch("ralphy.claude.subprocess.Popen") as mock_popen:
            mock_process = MagicMock()
            mock_process.stdout = MagicMock()
            mock_process.stdout.fileno.return_value = 0
            mock_process.stdout.read.return_value = ""
            mock_process.poll.return_value = 0
            mock_process.wait.return_value = 0
            mock_process.returncode = 0
            mock_process.pid = 12345
            mock_popen.return_value = mock_process

            runner = ClaudeRunner(working_dir=temp_project, model=None)
            runner.run("test prompt")

            # Verify Popen was called WITHOUT the model flag
            call_args = mock_popen.call_args
            cmd = call_args[0][0]  # First positional arg is the command list

            assert "--model" not in cmd

    def test_command_structure_with_model(self, temp_project):
        """Test la structure complète de la commande avec model."""
        with patch("ralphy.claude.subprocess.Popen") as mock_popen:
            mock_process = MagicMock()
            mock_process.stdout = MagicMock()
            mock_process.stdout.fileno.return_value = 0
            mock_process.stdout.read.return_value = ""
            mock_process.poll.return_value = 0
            mock_process.wait.return_value = 0
            mock_process.returncode = 0
            mock_process.pid = 12345
            mock_popen.return_value = mock_process

            runner = ClaudeRunner(working_dir=temp_project, model="haiku")
            runner.run("my test prompt")

            call_args = mock_popen.call_args
            cmd = call_args[0][0]

            # Verify expected command structure
            assert cmd[0] == "claude"
            assert "--print" in cmd
            assert "--dangerously-skip-permissions" in cmd
            assert "--model" in cmd
            assert "haiku" in cmd
            assert "-p" in cmd
            assert "my test prompt" in cmd
