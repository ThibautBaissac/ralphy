"""Tests pour les commandes CLI."""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from ralphy.cli import main
from ralphy.state import Phase, StateManager


FEATURE_NAME = "test-feature"


@pytest.fixture
def runner():
    """Create a Click CLI test runner."""
    return CliRunner()


@pytest.fixture
def project_with_prd(tmp_path):
    """Create a temporary project with PRD.md in feature directory."""
    feature_dir = tmp_path / "docs" / "features" / FEATURE_NAME
    feature_dir.mkdir(parents=True)
    prd = feature_dir / "PRD.md"
    prd.write_text("# Test PRD\n\nThis is a test product requirements document.")
    return tmp_path


@pytest.fixture
def project_without_prd(tmp_path):
    """Create a temporary project without PRD.md."""
    feature_dir = tmp_path / "docs" / "features" / FEATURE_NAME
    feature_dir.mkdir(parents=True)
    return tmp_path


class TestStatusCommand:
    """Tests for the status command."""

    def test_status_idle_project(self, runner, project_with_prd, monkeypatch):
        """Test status command on idle project."""
        monkeypatch.chdir(project_with_prd)
        result = runner.invoke(main, ["status", FEATURE_NAME])
        assert result.exit_code == 0
        assert "idle" in result.output.lower()

    def test_status_requires_feature_name(self, runner, project_with_prd, monkeypatch):
        """Test status command without feature name requires --all."""
        monkeypatch.chdir(project_with_prd)
        result = runner.invoke(main, ["status"])
        assert result.exit_code != 0

    def test_status_shows_phase(self, runner, project_with_prd, monkeypatch):
        """Test that status shows the current phase."""
        monkeypatch.chdir(project_with_prd)
        # Set up a specific state
        state_manager = StateManager(project_with_prd, FEATURE_NAME)
        state_manager.state.phase = Phase.IMPLEMENTATION
        state_manager.state.tasks_completed = 2
        state_manager.state.tasks_total = 5
        state_manager.save()

        result = runner.invoke(main, ["status", FEATURE_NAME])
        assert result.exit_code == 0
        assert "implementation" in result.output.lower()

    def test_status_shows_task_progress(self, runner, project_with_prd, monkeypatch):
        """Test that status shows task progress."""
        monkeypatch.chdir(project_with_prd)
        state_manager = StateManager(project_with_prd, FEATURE_NAME)
        state_manager.state.tasks_completed = 3
        state_manager.state.tasks_total = 10
        state_manager.save()

        result = runner.invoke(main, ["status", FEATURE_NAME])
        assert result.exit_code == 0
        assert "3/10" in result.output

    def test_status_all_features(self, runner, project_with_prd, monkeypatch):
        """Test status --all shows all features."""
        monkeypatch.chdir(project_with_prd)
        # Create another feature
        other_feature_dir = project_with_prd / "docs" / "features" / "other-feature"
        other_feature_dir.mkdir(parents=True)

        result = runner.invoke(main, ["status", "--all"])
        assert result.exit_code == 0
        assert FEATURE_NAME in result.output
        assert "other-feature" in result.output


class TestResetCommand:
    """Tests for the reset command."""

    def test_reset_confirmed(self, runner, project_with_prd, monkeypatch):
        """Test reset command when confirmed."""
        monkeypatch.chdir(project_with_prd)
        # Set up some state first
        state_manager = StateManager(project_with_prd, FEATURE_NAME)
        state_manager.state.phase = Phase.IMPLEMENTATION
        state_manager.save()

        # Confirm the reset
        result = runner.invoke(main, ["reset", FEATURE_NAME], input="y\n")
        assert result.exit_code == 0

        # Verify state was reset
        state_manager = StateManager(project_with_prd, FEATURE_NAME)
        assert state_manager.state.phase == Phase.IDLE

    def test_reset_cancelled(self, runner, project_with_prd, monkeypatch):
        """Test reset command when cancelled."""
        monkeypatch.chdir(project_with_prd)
        # Set up some state first
        state_manager = StateManager(project_with_prd, FEATURE_NAME)
        state_manager.state.phase = Phase.IMPLEMENTATION
        state_manager.save()

        # Cancel the reset
        result = runner.invoke(main, ["reset", FEATURE_NAME], input="n\n")
        assert result.exit_code == 0

        # Verify state was NOT reset
        state_manager = StateManager(project_with_prd, FEATURE_NAME)
        assert state_manager.state.phase == Phase.IMPLEMENTATION


class TestAbortCommand:
    """Tests for the abort command."""

    def test_abort_no_running_workflow(self, runner, project_with_prd, monkeypatch):
        """Test abort command when no workflow is running."""
        monkeypatch.chdir(project_with_prd)
        result = runner.invoke(main, ["abort", FEATURE_NAME])
        # Should succeed but report no process running
        assert result.exit_code == 0
        assert "aucun" in result.output.lower() or "no" in result.output.lower()

    def test_abort_running_workflow(self, runner, project_with_prd, monkeypatch):
        """Test abort command when a workflow is running."""
        monkeypatch.chdir(project_with_prd)
        # Set up a running state
        state_manager = StateManager(project_with_prd, FEATURE_NAME)
        state_manager.state.phase = Phase.IMPLEMENTATION
        state_manager.save()

        # Mock the abort function to avoid actual process killing
        with patch("ralphy.cli.abort_running_claude", return_value=False):
            result = runner.invoke(main, ["abort", FEATURE_NAME])
            assert result.exit_code == 0

        # Verify state was set to failed
        state_manager = StateManager(project_with_prd, FEATURE_NAME)
        assert state_manager.state.phase == Phase.FAILED

    def test_abort_awaiting_validation(self, runner, project_with_prd, monkeypatch):
        """Test abort command when awaiting validation."""
        monkeypatch.chdir(project_with_prd)
        # Set up awaiting validation state
        state_manager = StateManager(project_with_prd, FEATURE_NAME)
        state_manager.state.phase = Phase.AWAITING_SPEC_VALIDATION
        state_manager.save()

        result = runner.invoke(main, ["abort", FEATURE_NAME])
        assert result.exit_code == 0

        # Verify state was set to failed
        state_manager = StateManager(project_with_prd, FEATURE_NAME)
        assert state_manager.state.phase == Phase.FAILED


class TestStartCommand:
    """Tests for the start command."""

    def test_start_missing_prd(self, runner, project_without_prd, monkeypatch):
        """Test start command when PRD.md is missing."""
        monkeypatch.chdir(project_without_prd)
        with patch("ralphy.cli.check_claude_installed", return_value=True), \
             patch("ralphy.cli.check_git_installed", return_value=True), \
             patch("ralphy.cli.check_gh_installed", return_value=True):
            result = runner.invoke(main, ["start", FEATURE_NAME])
            assert result.exit_code != 0
            assert "prd" in result.output.lower()

    def test_start_missing_claude(self, runner, project_with_prd, monkeypatch):
        """Test start command when Claude CLI is not installed."""
        monkeypatch.chdir(project_with_prd)
        with patch("ralphy.cli.check_claude_installed", return_value=False):
            result = runner.invoke(main, ["start", FEATURE_NAME])
            assert result.exit_code != 0
            assert "claude" in result.output.lower()

    def test_start_missing_git(self, runner, project_with_prd, monkeypatch):
        """Test start command when git is not installed."""
        monkeypatch.chdir(project_with_prd)
        with patch("ralphy.cli.check_claude_installed", return_value=True), \
             patch("ralphy.cli.check_git_installed", return_value=False):
            result = runner.invoke(main, ["start", FEATURE_NAME])
            assert result.exit_code != 0
            assert "git" in result.output.lower()

    def test_start_missing_gh(self, runner, project_with_prd, monkeypatch):
        """Test start command when gh CLI is not installed."""
        monkeypatch.chdir(project_with_prd)
        with patch("ralphy.cli.check_claude_installed", return_value=True), \
             patch("ralphy.cli.check_git_installed", return_value=True), \
             patch("ralphy.cli.check_gh_installed", return_value=False):
            result = runner.invoke(main, ["start", FEATURE_NAME])
            assert result.exit_code != 0
            assert "gh" in result.output.lower()

    def test_start_already_running_cancelled(self, runner, project_with_prd, monkeypatch):
        """Test start command when workflow already running and user cancels."""
        monkeypatch.chdir(project_with_prd)
        # Set up a running state
        state_manager = StateManager(project_with_prd, FEATURE_NAME)
        state_manager.state.phase = Phase.IMPLEMENTATION
        state_manager.save()

        with patch("ralphy.cli.check_claude_installed", return_value=True), \
             patch("ralphy.cli.check_git_installed", return_value=True), \
             patch("ralphy.cli.check_gh_installed", return_value=True):
            # User says no to reset
            result = runner.invoke(main, ["start", FEATURE_NAME], input="n\n")
            assert result.exit_code == 0

            # State should still be IMPLEMENTATION
            state_manager = StateManager(project_with_prd, FEATURE_NAME)
            assert state_manager.state.phase == Phase.IMPLEMENTATION

    def test_start_invalid_feature_name(self, runner, project_with_prd, monkeypatch):
        """Test start command with invalid feature name."""
        monkeypatch.chdir(project_with_prd)
        with patch("ralphy.cli.check_claude_installed", return_value=True), \
             patch("ralphy.cli.check_git_installed", return_value=True), \
             patch("ralphy.cli.check_gh_installed", return_value=True):
            # Use underscore prefix which violates the regex pattern
            # (must start with alphanumeric, not underscore)
            result = runner.invoke(main, ["start", "_invalid-name"])
            assert result.exit_code != 0
            assert "invalid" in result.output.lower()


class TestVersionOption:
    """Tests for the version option."""

    def test_version_flag(self, runner):
        """Test --version flag."""
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert "ralphy" in result.output.lower()


class TestInitPromptsCommand:
    """Tests for the init-prompts command."""

    def test_init_prompts_creates_directory(self, runner, tmp_path):
        """Test that init-prompts creates .ralphy/prompts/ directory."""
        result = runner.invoke(main, ["init-prompts", str(tmp_path)])
        assert result.exit_code == 0

        prompts_dir = tmp_path / ".ralphy" / "prompts"
        assert prompts_dir.exists()
        assert prompts_dir.is_dir()

    def test_init_prompts_copies_all_prompts(self, runner, tmp_path):
        """Test that init-prompts copies all 4 prompt files."""
        result = runner.invoke(main, ["init-prompts", str(tmp_path)])
        assert result.exit_code == 0

        prompts_dir = tmp_path / ".ralphy" / "prompts"
        expected_files = ["spec_agent.md", "dev_agent.md", "qa_agent.md", "pr_agent.md"]

        for filename in expected_files:
            prompt_file = prompts_dir / filename
            assert prompt_file.exists(), f"{filename} should exist"
            content = prompt_file.read_text()
            # Should have header with placeholder documentation
            assert "CUSTOM PROMPT TEMPLATE" in content
            assert "Placeholder" in content
            # Should have EXIT_SIGNAL (from original content)
            assert "EXIT_SIGNAL" in content

    def test_init_prompts_does_not_overwrite_without_force(self, runner, tmp_path):
        """Test that init-prompts doesn't overwrite existing files without --force."""
        # Create directory and one existing file
        prompts_dir = tmp_path / ".ralphy" / "prompts"
        prompts_dir.mkdir(parents=True)
        existing_content = "# My custom prompt EXIT_SIGNAL preserved"
        (prompts_dir / "spec_agent.md").write_text(existing_content)

        result = runner.invoke(main, ["init-prompts", str(tmp_path)])
        assert result.exit_code == 0

        # spec_agent.md should not be overwritten
        assert (prompts_dir / "spec_agent.md").read_text() == existing_content

        # Other files should be created
        assert (prompts_dir / "dev_agent.md").exists()
        assert (prompts_dir / "qa_agent.md").exists()
        assert (prompts_dir / "pr_agent.md").exists()

        # Output should mention skipped file
        assert "skipping" in result.output.lower() or "skip" in result.output.lower()

    def test_init_prompts_force_overwrites(self, runner, tmp_path):
        """Test that init-prompts --force overwrites existing files."""
        # Create directory and one existing file
        prompts_dir = tmp_path / ".ralphy" / "prompts"
        prompts_dir.mkdir(parents=True)
        existing_content = "# My custom prompt that will be overwritten"
        (prompts_dir / "spec_agent.md").write_text(existing_content)

        result = runner.invoke(main, ["init-prompts", "--force", str(tmp_path)])
        assert result.exit_code == 0

        # spec_agent.md should be overwritten
        new_content = (prompts_dir / "spec_agent.md").read_text()
        assert new_content != existing_content
        assert "CUSTOM PROMPT TEMPLATE" in new_content

    def test_init_prompts_default_path(self, runner, tmp_path, monkeypatch):
        """Test that init-prompts uses current directory if no path given."""
        # Change to tmp_path
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(main, ["init-prompts"])
        assert result.exit_code == 0

        prompts_dir = tmp_path / ".ralphy" / "prompts"
        assert prompts_dir.exists()
        assert (prompts_dir / "spec_agent.md").exists()

    def test_init_prompts_adds_header_with_placeholders(self, runner, tmp_path):
        """Test that init-prompts adds header documenting placeholders."""
        result = runner.invoke(main, ["init-prompts", str(tmp_path)])
        assert result.exit_code == 0

        # Check spec_agent.md has spec-specific placeholders
        spec_content = (tmp_path / ".ralphy" / "prompts" / "spec_agent.md").read_text()
        assert "{{prd_content}}" in spec_content
        assert "{{project_name}}" in spec_content

        # Check dev_agent.md has dev-specific placeholders
        dev_content = (tmp_path / ".ralphy" / "prompts" / "dev_agent.md").read_text()
        assert "{{spec_content}}" in dev_content
        assert "{{tasks_content}}" in dev_content
        assert "{{resume_instruction}}" in dev_content

        # Check pr_agent.md has pr-specific placeholders
        pr_content = (tmp_path / ".ralphy" / "prompts" / "pr_agent.md").read_text()
        assert "{{branch_name}}" in pr_content
        assert "{{qa_report}}" in pr_content
