"""Tests pour les commandes CLI."""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from click.testing import CliRunner

from ralphy.cli import description_to_feature_name, generate_quick_prd, main
from ralphy.config import load_config
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


class TestInitConfigCommand:
    """Tests for the init-config command."""

    def test_init_config_creates_directory(self, runner, tmp_path):
        """Test that init-config creates .ralphy/ directory."""
        result = runner.invoke(main, ["init-config", str(tmp_path)])
        assert result.exit_code == 0

        ralphy_dir = tmp_path / ".ralphy"
        assert ralphy_dir.exists()
        assert ralphy_dir.is_dir()

    def test_init_config_creates_config_file(self, runner, tmp_path):
        """Test that init-config creates config.yaml file."""
        result = runner.invoke(main, ["init-config", str(tmp_path)])
        assert result.exit_code == 0

        config_path = tmp_path / ".ralphy" / "config.yaml"
        assert config_path.exists()
        assert "Created" in result.output

    def test_init_config_contains_all_sections(self, runner, tmp_path):
        """Test that init-config creates config with all required sections."""
        result = runner.invoke(main, ["init-config", str(tmp_path)])
        assert result.exit_code == 0

        content = (tmp_path / ".ralphy" / "config.yaml").read_text()

        # Check all major sections are present
        assert "project:" in content
        assert "models:" in content
        assert "stack:" in content
        assert "timeouts:" in content
        assert "retry:" in content
        assert "circuit_breaker:" in content

    def test_init_config_does_not_overwrite_without_force(self, runner, tmp_path):
        """Test that init-config doesn't overwrite existing file without --force."""
        # Create existing config
        ralphy_dir = tmp_path / ".ralphy"
        ralphy_dir.mkdir(parents=True)
        config_path = ralphy_dir / "config.yaml"
        original_content = "# My custom config\nproject:\n  name: custom"
        config_path.write_text(original_content)

        result = runner.invoke(main, ["init-config", str(tmp_path)])
        assert result.exit_code == 0

        # Original content should be preserved
        assert config_path.read_text() == original_content
        assert "already exists" in result.output.lower()
        assert "--force" in result.output

    def test_init_config_force_overwrites(self, runner, tmp_path):
        """Test that init-config --force overwrites existing file."""
        # Create existing config
        ralphy_dir = tmp_path / ".ralphy"
        ralphy_dir.mkdir(parents=True)
        config_path = ralphy_dir / "config.yaml"
        original_content = "# My custom config that will be overwritten"
        config_path.write_text(original_content)

        result = runner.invoke(main, ["init-config", "--force", str(tmp_path)])
        assert result.exit_code == 0

        # Config should be overwritten
        new_content = config_path.read_text()
        assert new_content != original_content
        assert "RALPHY CONFIGURATION" in new_content

    def test_init_config_default_path(self, runner, tmp_path, monkeypatch):
        """Test that init-config uses current directory if no path given."""
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(main, ["init-config"])
        assert result.exit_code == 0

        config_path = tmp_path / ".ralphy" / "config.yaml"
        assert config_path.exists()

    def test_init_config_has_comments(self, runner, tmp_path):
        """Test that init-config creates config with documentation comments."""
        result = runner.invoke(main, ["init-config", str(tmp_path)])
        assert result.exit_code == 0

        content = (tmp_path / ".ralphy" / "config.yaml").read_text()

        # Should have header comments
        assert "RALPHY CONFIGURATION" in content
        # Should have section comments
        assert "Project Settings" in content
        assert "Model Configuration" in content
        assert "Timeouts" in content
        assert "Circuit Breaker" in content
        # Should have inline value comments
        assert "# 30 min" in content or "30 min" in content

    def test_init_config_is_valid_yaml(self, runner, tmp_path):
        """Test that generated config is valid YAML."""
        result = runner.invoke(main, ["init-config", str(tmp_path)])
        assert result.exit_code == 0

        config_path = tmp_path / ".ralphy" / "config.yaml"
        content = config_path.read_text()

        # Should parse without errors
        parsed = yaml.safe_load(content)
        assert parsed is not None
        assert isinstance(parsed, dict)

    def test_init_config_loads_correctly(self, runner, tmp_path):
        """Test that generated config loads correctly with load_config."""
        result = runner.invoke(main, ["init-config", str(tmp_path)])
        assert result.exit_code == 0

        # load_config should work without errors
        config = load_config(tmp_path)
        assert config is not None

        # Check some default values are set correctly
        assert config.name == "my-project"
        assert config.models.specification == "sonnet"
        assert config.stack.language == "typescript"

    def test_init_config_uses_constant_values(self, runner, tmp_path):
        """Test that generated config uses actual values from constants."""
        from ralphy.constants import (
            SPEC_TIMEOUT_SECONDS,
            IMPL_TIMEOUT_SECONDS,
            CB_INACTIVITY_TIMEOUT_SECONDS,
            CB_MAX_ATTEMPTS,
        )

        result = runner.invoke(main, ["init-config", str(tmp_path)])
        assert result.exit_code == 0

        config_path = tmp_path / ".ralphy" / "config.yaml"
        parsed = yaml.safe_load(config_path.read_text())

        # Verify values match constants
        assert parsed["timeouts"]["specification"] == SPEC_TIMEOUT_SECONDS
        assert parsed["timeouts"]["implementation"] == IMPL_TIMEOUT_SECONDS
        assert parsed["circuit_breaker"]["inactivity_timeout"] == CB_INACTIVITY_TIMEOUT_SECONDS
        assert parsed["circuit_breaker"]["max_attempts"] == CB_MAX_ATTEMPTS


class TestDescriptionToFeatureName:
    """Tests for the description_to_feature_name function."""

    def test_simple_description(self):
        """Test converting a simple description to slug."""
        assert description_to_feature_name("implement user login") == "implement-user-login"

    def test_special_characters(self):
        """Test handling of special characters."""
        assert description_to_feature_name("add auth with OAuth 2.0!") == "add-auth-with-oauth-2-0"

    def test_uppercase_to_lowercase(self):
        """Test uppercase conversion to lowercase."""
        assert description_to_feature_name("Add User Authentication") == "add-user-authentication"

    def test_max_length_truncation(self):
        """Test truncation at max length without breaking words."""
        long_desc = "implement a very long feature with many words in the description"
        result = description_to_feature_name(long_desc, max_length=20)
        assert len(result) <= 20
        # Should not end with a hyphen (truncated mid-word)
        assert not result.endswith("-")

    def test_empty_description_raises_error(self):
        """Test that empty description raises ValueError."""
        with pytest.raises(ValueError, match="empty"):
            description_to_feature_name("")

    def test_whitespace_only_raises_error(self):
        """Test that whitespace-only description raises ValueError."""
        with pytest.raises(ValueError, match="empty"):
            description_to_feature_name("   ")

    def test_special_only_raises_error(self):
        """Test that description with only special chars raises ValueError."""
        with pytest.raises(ValueError, match="Cannot derive"):
            description_to_feature_name("!@#$%^&*()")

    def test_unicode_normalization(self):
        """Test handling of unicode characters."""
        # Accented characters should be normalized to ASCII
        assert description_to_feature_name("café authentication") == "cafe-authentication"

    def test_multiple_hyphens_collapsed(self):
        """Test that multiple consecutive hyphens are collapsed."""
        assert description_to_feature_name("add   multiple   spaces") == "add-multiple-spaces"


class TestGenerateQuickPrd:
    """Tests for the generate_quick_prd function."""

    def test_basic_prd_generation(self):
        """Test basic PRD generation."""
        content = generate_quick_prd("implement user login")
        assert "# implement user login" in content
        assert "## Objective" in content
        assert "## Requirements" in content
        assert "Ralphy Quick Start mode" in content

    def test_prd_strips_whitespace(self):
        """Test that PRD strips leading/trailing whitespace from description."""
        content = generate_quick_prd("  implement feature  ")
        assert "# implement feature" in content


class TestQuickStartCommand:
    """Tests for quick start mode in the start command."""

    def test_quick_start_creates_prd(self, runner, tmp_path, monkeypatch):
        """Test that quick start mode creates PRD.md from description."""
        monkeypatch.chdir(tmp_path)

        with patch("ralphy.cli.check_claude_installed", return_value=True), \
             patch("ralphy.cli.check_git_installed", return_value=True), \
             patch("ralphy.cli.check_gh_installed", return_value=True), \
             patch("ralphy.cli.Orchestrator") as mock_orch:
            # Make orchestrator.run() return True
            mock_instance = mock_orch.return_value
            mock_instance.run.return_value = True

            result = runner.invoke(main, ["start", "implement user login"])
            assert result.exit_code == 0

            # Check PRD was created
            prd_path = tmp_path / "docs" / "features" / "implement-user-login" / "PRD.md"
            assert prd_path.exists()
            content = prd_path.read_text()
            assert "# implement user login" in content
            assert "quick start" in result.output.lower()

    def test_existing_feature_takes_precedence(self, runner, tmp_path, monkeypatch):
        """Test that existing feature with PRD takes precedence over quick start."""
        monkeypatch.chdir(tmp_path)

        # Create existing feature with PRD
        feature_dir = tmp_path / "docs" / "features" / "my-feature"
        feature_dir.mkdir(parents=True)
        prd_path = feature_dir / "PRD.md"
        original_content = "# My Custom PRD\n\nCustom content"
        prd_path.write_text(original_content)

        with patch("ralphy.cli.check_claude_installed", return_value=True), \
             patch("ralphy.cli.check_git_installed", return_value=True), \
             patch("ralphy.cli.check_gh_installed", return_value=True), \
             patch("ralphy.cli.Orchestrator") as mock_orch:
            mock_instance = mock_orch.return_value
            mock_instance.run.return_value = True

            result = runner.invoke(main, ["start", "my-feature"])
            assert result.exit_code == 0

            # Original PRD should be preserved
            assert prd_path.read_text() == original_content
            # Should not mention quick start
            assert "quick start" not in result.output.lower()

    def test_derived_name_conflict_uses_existing_prd(self, runner, tmp_path, monkeypatch):
        """Test that when derived name conflicts with existing feature, existing PRD is used."""
        monkeypatch.chdir(tmp_path)

        # Create existing feature that would conflict with derived name
        feature_dir = tmp_path / "docs" / "features" / "implement-auth"
        feature_dir.mkdir(parents=True)
        prd_path = feature_dir / "PRD.md"
        original_content = "# Existing Auth PRD"
        prd_path.write_text(original_content)

        with patch("ralphy.cli.check_claude_installed", return_value=True), \
             patch("ralphy.cli.check_git_installed", return_value=True), \
             patch("ralphy.cli.check_gh_installed", return_value=True), \
             patch("ralphy.cli.Orchestrator") as mock_orch:
            mock_instance = mock_orch.return_value
            mock_instance.run.return_value = True

            # Pass description that would derive to "implement-auth"
            result = runner.invoke(main, ["start", "implement auth"])
            assert result.exit_code == 0

            # Original PRD should be preserved
            assert prd_path.read_text() == original_content
            # Should warn about existing feature
            assert "already exists" in result.output.lower()

    def test_quick_start_with_invalid_description(self, runner, tmp_path, monkeypatch):
        """Test that invalid description that can't be converted to slug fails."""
        monkeypatch.chdir(tmp_path)

        with patch("ralphy.cli.check_claude_installed", return_value=True), \
             patch("ralphy.cli.check_git_installed", return_value=True), \
             patch("ralphy.cli.check_gh_installed", return_value=True):
            result = runner.invoke(main, ["start", "!@#$%"])
            assert result.exit_code != 0
            assert "cannot derive" in result.output.lower()

    def test_feature_name_without_prd_triggers_quick_start(self, runner, tmp_path, monkeypatch):
        """Test that valid feature name without PRD triggers quick start."""
        monkeypatch.chdir(tmp_path)

        with patch("ralphy.cli.check_claude_installed", return_value=True), \
             patch("ralphy.cli.check_git_installed", return_value=True), \
             patch("ralphy.cli.check_gh_installed", return_value=True), \
             patch("ralphy.cli.Orchestrator") as mock_orch:
            mock_instance = mock_orch.return_value
            mock_instance.run.return_value = True

            # Use a valid feature name pattern but no existing PRD
            result = runner.invoke(main, ["start", "new-feature"])
            assert result.exit_code == 0

            # PRD should be created
            prd_path = tmp_path / "docs" / "features" / "new-feature" / "PRD.md"
            assert prd_path.exists()
            assert "quick start" in result.output.lower()
