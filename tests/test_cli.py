"""Tests pour les commandes CLI."""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from ralphy.cli import main
from ralphy.state import Phase, StateManager


@pytest.fixture
def runner():
    """Create a Click CLI test runner."""
    return CliRunner()


@pytest.fixture
def project_with_prd(tmp_path):
    """Create a temporary project with PRD.md."""
    prd = tmp_path / "PRD.md"
    prd.write_text("# Test PRD\n\nThis is a test product requirements document.")
    return tmp_path


@pytest.fixture
def project_without_prd(tmp_path):
    """Create a temporary project without PRD.md."""
    return tmp_path


class TestStatusCommand:
    """Tests for the status command."""

    def test_status_idle_project(self, runner, project_with_prd):
        """Test status command on idle project."""
        result = runner.invoke(main, ["status", str(project_with_prd)])
        assert result.exit_code == 0
        assert "idle" in result.output.lower()

    def test_status_nonexistent_project(self, runner, tmp_path):
        """Test status command on non-existent project."""
        nonexistent = tmp_path / "nonexistent"
        result = runner.invoke(main, ["status", str(nonexistent)])
        assert result.exit_code != 0

    def test_status_shows_phase(self, runner, project_with_prd):
        """Test that status shows the current phase."""
        # Set up a specific state
        state_manager = StateManager(project_with_prd)
        state_manager.state.phase = Phase.IMPLEMENTATION
        state_manager.state.tasks_completed = 2
        state_manager.state.tasks_total = 5
        state_manager.save()

        result = runner.invoke(main, ["status", str(project_with_prd)])
        assert result.exit_code == 0
        assert "implementation" in result.output.lower()

    def test_status_shows_task_progress(self, runner, project_with_prd):
        """Test that status shows task progress."""
        state_manager = StateManager(project_with_prd)
        state_manager.state.tasks_completed = 3
        state_manager.state.tasks_total = 10
        state_manager.save()

        result = runner.invoke(main, ["status", str(project_with_prd)])
        assert result.exit_code == 0
        assert "3/10" in result.output


class TestResetCommand:
    """Tests for the reset command."""

    def test_reset_confirmed(self, runner, project_with_prd):
        """Test reset command when confirmed."""
        # Set up some state first
        state_manager = StateManager(project_with_prd)
        state_manager.state.phase = Phase.IMPLEMENTATION
        state_manager.save()

        # Confirm the reset
        result = runner.invoke(main, ["reset", str(project_with_prd)], input="y\n")
        assert result.exit_code == 0

        # Verify state was reset
        state_manager = StateManager(project_with_prd)
        assert state_manager.state.phase == Phase.IDLE

    def test_reset_cancelled(self, runner, project_with_prd):
        """Test reset command when cancelled."""
        # Set up some state first
        state_manager = StateManager(project_with_prd)
        state_manager.state.phase = Phase.IMPLEMENTATION
        state_manager.save()

        # Cancel the reset
        result = runner.invoke(main, ["reset", str(project_with_prd)], input="n\n")
        assert result.exit_code == 0

        # Verify state was NOT reset
        state_manager = StateManager(project_with_prd)
        assert state_manager.state.phase == Phase.IMPLEMENTATION


class TestAbortCommand:
    """Tests for the abort command."""

    def test_abort_no_running_workflow(self, runner, project_with_prd):
        """Test abort command when no workflow is running."""
        result = runner.invoke(main, ["abort", str(project_with_prd)])
        # Should succeed but report no process running
        assert result.exit_code == 0
        assert "aucun" in result.output.lower() or "no" in result.output.lower()

    def test_abort_running_workflow(self, runner, project_with_prd):
        """Test abort command when a workflow is running."""
        # Set up a running state
        state_manager = StateManager(project_with_prd)
        state_manager.state.phase = Phase.IMPLEMENTATION
        state_manager.save()

        # Mock the abort function to avoid actual process killing
        with patch("ralphy.cli.abort_running_claude", return_value=False):
            result = runner.invoke(main, ["abort", str(project_with_prd)])
            assert result.exit_code == 0

        # Verify state was set to failed
        state_manager = StateManager(project_with_prd)
        assert state_manager.state.phase == Phase.FAILED

    def test_abort_awaiting_validation(self, runner, project_with_prd):
        """Test abort command when awaiting validation."""
        # Set up awaiting validation state
        state_manager = StateManager(project_with_prd)
        state_manager.state.phase = Phase.AWAITING_SPEC_VALIDATION
        state_manager.save()

        result = runner.invoke(main, ["abort", str(project_with_prd)])
        assert result.exit_code == 0

        # Verify state was set to failed
        state_manager = StateManager(project_with_prd)
        assert state_manager.state.phase == Phase.FAILED


class TestStartCommand:
    """Tests for the start command."""

    def test_start_missing_prd(self, runner, project_without_prd):
        """Test start command when PRD.md is missing."""
        with patch("ralphy.cli.check_claude_installed", return_value=True), \
             patch("ralphy.cli.check_git_installed", return_value=True), \
             patch("ralphy.cli.check_gh_installed", return_value=True):
            result = runner.invoke(main, ["start", str(project_without_prd)])
            assert result.exit_code != 0
            assert "prd" in result.output.lower()

    def test_start_missing_claude(self, runner, project_with_prd):
        """Test start command when Claude CLI is not installed."""
        with patch("ralphy.cli.check_claude_installed", return_value=False):
            result = runner.invoke(main, ["start", str(project_with_prd)])
            assert result.exit_code != 0
            assert "claude" in result.output.lower()

    def test_start_missing_git(self, runner, project_with_prd):
        """Test start command when git is not installed."""
        with patch("ralphy.cli.check_claude_installed", return_value=True), \
             patch("ralphy.cli.check_git_installed", return_value=False):
            result = runner.invoke(main, ["start", str(project_with_prd)])
            assert result.exit_code != 0
            assert "git" in result.output.lower()

    def test_start_missing_gh(self, runner, project_with_prd):
        """Test start command when gh CLI is not installed."""
        with patch("ralphy.cli.check_claude_installed", return_value=True), \
             patch("ralphy.cli.check_git_installed", return_value=True), \
             patch("ralphy.cli.check_gh_installed", return_value=False):
            result = runner.invoke(main, ["start", str(project_with_prd)])
            assert result.exit_code != 0
            assert "gh" in result.output.lower()

    def test_start_already_running_cancelled(self, runner, project_with_prd):
        """Test start command when workflow already running and user cancels."""
        # Set up a running state
        state_manager = StateManager(project_with_prd)
        state_manager.state.phase = Phase.IMPLEMENTATION
        state_manager.save()

        with patch("ralphy.cli.check_claude_installed", return_value=True), \
             patch("ralphy.cli.check_git_installed", return_value=True), \
             patch("ralphy.cli.check_gh_installed", return_value=True):
            # User says no to reset
            result = runner.invoke(main, ["start", str(project_with_prd)], input="n\n")
            assert result.exit_code == 0

            # State should still be IMPLEMENTATION
            state_manager = StateManager(project_with_prd)
            assert state_manager.state.phase == Phase.IMPLEMENTATION


class TestVersionOption:
    """Tests for the version option."""

    def test_version_flag(self, runner):
        """Test --version flag."""
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert "ralphy" in result.output.lower()
