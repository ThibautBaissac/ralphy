"""Tests for the progress module."""

from datetime import datetime

import pytest
from rich.panel import Panel
from rich.progress import Progress

from ralphy.activity import (
    Activity,
    ActivityType,
    OutputParser,
    match_agent_name,
    normalize_agent_name,
)
from ralphy.progress import (
    ProgressDisplay,
    ProgressRenderer,
    ProgressState,
    RenderContext,
)


class TestActivityType:
    """Tests for ActivityType enum."""

    def test_activity_values(self):
        """Verifies enum values."""
        assert ActivityType.IDLE.value == "idle"
        assert ActivityType.WRITING_FILE.value == "writing_file"
        assert ActivityType.RUNNING_TEST.value == "running_test"
        assert ActivityType.RUNNING_COMMAND.value == "running_command"
        assert ActivityType.TASK_COMPLETE.value == "task_complete"


class TestActivity:
    """Tests for Activity dataclass."""

    def test_activity_creation(self):
        """Tests activity creation."""
        activity = Activity(
            type=ActivityType.WRITING_FILE,
            description="Writing app/models/user.rb",
            detail="app/models/user.rb",
        )
        assert activity.type == ActivityType.WRITING_FILE
        assert activity.description == "Writing app/models/user.rb"
        assert activity.detail == "app/models/user.rb"

    def test_activity_without_detail(self):
        """Tests activity without detail."""
        activity = Activity(
            type=ActivityType.RUNNING_TEST,
            description="Running tests",
        )
        assert activity.detail is None


class TestOutputParser:
    """Tests for OutputParser."""

    def test_detect_writing_file(self):
        """Tests file write detection."""
        parser = OutputParser()

        # Pattern Writing
        activity = parser.parse("Writing `app/models/user.rb`")
        assert activity is not None
        assert activity.type == ActivityType.WRITING_FILE
        assert "app/models/user.rb" in activity.description

        # Pattern Creating
        activity = parser.parse("Creating app/controllers/api.py")
        assert activity is not None
        assert activity.type == ActivityType.WRITING_FILE

    def test_detect_running_test(self):
        """Tests test execution detection."""
        parser = OutputParser()

        activity = parser.parse("bundle exec rspec spec/models/user_spec.rb")
        assert activity is not None
        assert activity.type == ActivityType.RUNNING_TEST

        activity = parser.parse("Running tests...")
        assert activity is not None
        assert activity.type == ActivityType.RUNNING_TEST

        activity = parser.parse("5 examples, 0 failures")
        assert activity is not None
        assert activity.type == ActivityType.RUNNING_TEST

    def test_detect_running_command(self):
        """Tests command execution detection."""
        parser = OutputParser()

        activity = parser.parse("Running: bundle install")
        assert activity is not None
        assert activity.type == ActivityType.RUNNING_COMMAND

        activity = parser.parse("$ git status")
        assert activity is not None
        assert activity.type == ActivityType.RUNNING_COMMAND

    def test_detect_task_complete(self):
        """Test task completion detection."""
        parser = OutputParser()

        activity = parser.parse("**Status**: completed")
        assert activity is not None
        assert activity.type == ActivityType.TASK_COMPLETE

        activity = parser.parse("✓ Task 1 completed")
        assert activity is not None
        assert activity.type == ActivityType.TASK_COMPLETE

    def test_no_activity_detected(self):
        """Test quand aucune activité n'est détectée."""
        parser = OutputParser()

        activity = parser.parse("Just some random text")
        assert activity is None

        activity = parser.parse("")
        assert activity is None


class TestProgressState:
    """Tests pour ProgressState."""

    def test_default_state(self):
        """Test état par défaut."""
        state = ProgressState()
        assert state.phase_name == ""
        assert state.phase_progress == 0.0
        assert state.tasks_completed == 0
        assert state.tasks_total == 0
        assert state.current_activity is None
        assert state.last_output_lines == []


class TestProgressDisplay:
    """Tests pour ProgressDisplay."""

    def test_init(self):
        """Test initialisation."""
        display = ProgressDisplay()
        assert not display.is_active

    def test_start_stop(self):
        """Test démarrage et arrêt."""
        display = ProgressDisplay()

        display.start("IMPLEMENTATION", 10)
        assert display.is_active

        display.stop()
        assert not display.is_active

    def test_update_tasks(self):
        """Test mise à jour des tâches."""
        display = ProgressDisplay()
        display.start("IMPLEMENTATION", 10)

        display.update_tasks(5, 10)
        # Vérifie que le state interne est mis à jour
        assert display._state.tasks_completed == 5
        assert display._state.tasks_total == 10

        display.stop()

    def test_process_output_detects_activity(self):
        """Test que process_output détecte les activités."""
        display = ProgressDisplay()
        display.start("IMPLEMENTATION", 10)

        display.process_output("Writing app/models/user.rb")
        assert display._state.current_activity is not None
        assert display._state.current_activity.type == ActivityType.WRITING_FILE

        display.stop()

    def test_process_output_fires_callback_on_completion(self):
        """Test that task completion triggers callback (orchestrator handles counter)."""
        callback_events = []

        def on_task_event(event_type, task_id, task_name):
            callback_events.append((event_type, task_id, task_name))

        display = ProgressDisplay(on_task_event=on_task_event)
        display.start("IMPLEMENTATION", 10)

        display.process_output("**Status**: completed")
        # Callback should be fired (orchestrator will update counter via update_tasks)
        assert len(callback_events) == 1
        assert callback_events[0][0] == "complete"

        # Counter is NOT incremented locally - orchestrator handles this
        assert display._state.tasks_completed == 0

        # Orchestrator would call update_tasks with authoritative count
        display.update_tasks(1, 10)
        assert display._state.tasks_completed == 1

        display.stop()

    def test_process_output_keeps_last_lines(self):
        """Test que les dernières lignes sont gardées."""
        display = ProgressDisplay()
        display.start("IMPLEMENTATION", 10)

        display.process_output("Line 1\nLine 2\nLine 3\nLine 4\nLine 5")
        # MAX_OUTPUT_LINES = 3
        assert len(display._state.last_output_lines) <= 3

        display.stop()

    def test_update_phase_progress(self):
        """Test mise à jour de la progression de phase."""
        display = ProgressDisplay()
        display.start("IMPLEMENTATION", 10)

        display.update_phase_progress(50.0)
        assert display._state.phase_progress == 50.0

        # Test clamping
        display.update_phase_progress(150.0)
        assert display._state.phase_progress == 100.0

        display.update_phase_progress(-10.0)
        assert display._state.phase_progress == 0.0

        display.stop()


class TestProgressStateNewFields:
    """Tests pour les nouveaux champs de ProgressState."""

    def test_new_fields_defaults(self):
        """Test que les nouveaux champs ont des valeurs par défaut."""
        state = ProgressState()
        assert state.model_name == ""
        assert state.phase_started_at is None
        assert state.phase_timeout == 0
        assert state.feature_name == ""

    def test_new_fields_initialization(self):
        """Test l'initialisation des nouveaux champs."""
        now = datetime.now()
        state = ProgressState(
            phase_name="IMPLEMENTATION",
            model_name="opus",
            phase_started_at=now,
            phase_timeout=14400,
            feature_name="user-auth",
        )
        assert state.model_name == "opus"
        assert state.phase_started_at == now
        assert state.phase_timeout == 14400
        assert state.feature_name == "user-auth"


class TestTimeFormattingHelpers:
    """Tests for time formatting functions in ProgressRenderer."""

    def test_format_elapsed_seconds_only(self):
        """Test formatting for less than a minute."""
        assert ProgressRenderer.format_elapsed(45) == "00:45"
        assert ProgressRenderer.format_elapsed(0) == "00:00"
        assert ProgressRenderer.format_elapsed(59) == "00:59"

    def test_format_elapsed_minutes_and_seconds(self):
        """Test formatting with minutes and seconds."""
        assert ProgressRenderer.format_elapsed(65) == "01:05"
        assert ProgressRenderer.format_elapsed(130) == "02:10"
        assert ProgressRenderer.format_elapsed(3599) == "59:59"

    def test_format_elapsed_hours(self):
        """Test formatting with hours."""
        assert ProgressRenderer.format_elapsed(3600) == "1h00m00s"
        assert ProgressRenderer.format_elapsed(3661) == "1h01m01s"
        assert ProgressRenderer.format_elapsed(7325) == "2h02m05s"

    def test_format_timeout_minutes_only(self):
        """Test timeout formatting in minutes."""
        assert ProgressRenderer.format_timeout(1800) == "30m"
        assert ProgressRenderer.format_timeout(600) == "10m"
        assert ProgressRenderer.format_timeout(60) == "1m"

    def test_format_timeout_hours(self):
        """Test timeout formatting in hours."""
        assert ProgressRenderer.format_timeout(3600) == "1h00m"
        assert ProgressRenderer.format_timeout(7200) == "2h00m"
        assert ProgressRenderer.format_timeout(14400) == "4h00m"
        assert ProgressRenderer.format_timeout(5400) == "1h30m"


class TestProgressDisplayStart:
    """Tests pour la méthode start avec les nouveaux paramètres."""

    def test_start_with_new_params(self):
        """Test démarrage avec les nouveaux paramètres."""
        display = ProgressDisplay()
        display.start(
            "IMPLEMENTATION",
            total_tasks=10,
            model="opus",
            timeout=14400,
            feature_name="user-auth",
        )

        assert display._state.phase_name == "IMPLEMENTATION"
        assert display._state.model_name == "opus"
        assert display._state.phase_timeout == 14400
        assert display._state.feature_name == "user-auth"
        assert display._state.phase_started_at is not None

        display.stop()

    def test_start_without_new_params(self):
        """Test démarrage sans les nouveaux paramètres (backward compatibility)."""
        display = ProgressDisplay()
        display.start("SPECIFICATION", 5)

        assert display._state.phase_name == "SPECIFICATION"
        assert display._state.model_name == ""
        assert display._state.phase_timeout == 0
        assert display._state.feature_name == ""
        assert display._state.phase_started_at is not None

        display.stop()


class TestRenderContext:
    """Tests for RenderContext dataclass."""

    def test_render_context_creation(self):
        """Test creating a RenderContext with all fields."""
        state = ProgressState(phase_name="IMPLEMENTATION")
        phase_progress = Progress()
        tasks_progress = Progress()

        context = RenderContext(
            state=state,
            phase_progress=phase_progress,
            tasks_progress=tasks_progress,
            phase_task_id=1,
            tasks_task_id=2,
        )

        assert context.state is state
        assert context.phase_progress is phase_progress
        assert context.tasks_progress is tasks_progress
        assert context.phase_task_id == 1
        assert context.tasks_task_id == 2

    def test_render_context_with_none_task_ids(self):
        """Test RenderContext with None task IDs."""
        state = ProgressState()
        context = RenderContext(
            state=state,
            phase_progress=Progress(),
            tasks_progress=Progress(),
            phase_task_id=None,
            tasks_task_id=None,
        )

        assert context.phase_task_id is None
        assert context.tasks_task_id is None


class TestProgressStateAgent:
    """Tests for agent fields in ProgressState."""

    def test_progress_state_includes_agent_field(self):
        """Test that ProgressState includes agent fields."""
        state = ProgressState(
            phase_name="IMPLEMENTATION",
            agent_name="dev-agent",
        )
        assert state.agent_name == "dev-agent"

    def test_progress_state_agent_defaults_to_empty(self):
        """Test that agent_name defaults to empty."""
        state = ProgressState()
        assert state.agent_name == ""
        assert state.available_agents == []

    def test_progress_state_with_available_agents(self):
        """Test ProgressState with available agents list."""
        state = ProgressState(
            phase_name="IMPLEMENTATION",
            agent_name="dev-agent",
            available_agents=["backend", "frontend", "test"],
        )
        assert state.available_agents == ["backend", "frontend", "test"]
        assert len(state.available_agents) == 3


class TestProgressDisplayAgent:
    """Tests for agent parameters in ProgressDisplay.start()."""

    def test_start_with_agent_name(self):
        """Test start() with agent name."""
        display = ProgressDisplay()
        display.start(
            "IMPLEMENTATION",
            total_tasks=5,
            agent_name="dev-agent",
        )
        assert display._state.agent_name == "dev-agent"
        display.stop()

    def test_start_with_available_agents(self):
        """Test start() with available agents list."""
        display = ProgressDisplay()
        display.start(
            "IMPLEMENTATION",
            agent_name="dev-agent",
            available_agents=["backend", "frontend"],
        )
        assert display._state.available_agents == ["backend", "frontend"]
        display.stop()

    def test_start_with_none_available_agents(self):
        """Test that None available_agents becomes empty list."""
        display = ProgressDisplay()
        display.start("IMPLEMENTATION", agent_name="dev-agent", available_agents=None)
        assert display._state.available_agents == []
        display.stop()

    def test_update_available_agents(self):
        """Test updating available agents after start."""
        display = ProgressDisplay()
        display.start("IMPLEMENTATION", agent_name="dev-agent")
        assert display._state.available_agents == []

        display.update_available_agents(["backend", "frontend", "test-agent"])
        assert display._state.available_agents == ["backend", "frontend", "test-agent"]
        assert len(display._state.available_agents) == 3
        display.stop()


class TestProgressRendererAgent:
    """Tests for agent rendering in ProgressRenderer."""

    def test_render_shows_agent(self):
        """Test rendering with agent name."""
        renderer = ProgressRenderer()
        state = ProgressState(
            phase_name="IMPLEMENTATION",
            agent_name="dev-agent",
        )
        phase_progress = Progress()
        phase_task_id = phase_progress.add_task("IMPLEMENTATION", total=100, completed=0)

        context = RenderContext(
            state=state,
            phase_progress=phase_progress,
            tasks_progress=Progress(),
            phase_task_id=phase_task_id,
            tasks_task_id=None,
        )

        result = renderer.render(context)
        assert result is not None

    def test_render_shows_available_agents_count(self):
        """Test rendering shows available agents count."""
        renderer = ProgressRenderer()
        state = ProgressState(
            phase_name="IMPLEMENTATION",
            agent_name="dev-agent",
            available_agents=["backend", "frontend"],
        )
        phase_progress = Progress()
        phase_task_id = phase_progress.add_task("IMPLEMENTATION", total=100, completed=0)

        context = RenderContext(
            state=state,
            phase_progress=phase_progress,
            tasks_progress=Progress(),
            phase_task_id=phase_task_id,
            tasks_task_id=None,
        )

        result = renderer.render(context)
        assert result is not None

    def test_render_without_agent_name_skips_line(self):
        """Test that agent line is skipped when agent_name is empty."""
        renderer = ProgressRenderer()
        state = ProgressState(
            phase_name="IMPLEMENTATION",
            agent_name="",  # No agent name
        )
        phase_progress = Progress()
        phase_task_id = phase_progress.add_task("IMPLEMENTATION", total=100, completed=0)

        context = RenderContext(
            state=state,
            phase_progress=phase_progress,
            tasks_progress=Progress(),
            phase_task_id=phase_task_id,
            tasks_task_id=None,
        )

        result = renderer.render(context)
        assert result is not None


class TestProgressRenderer:
    """Tests for ProgressRenderer class."""

    def test_renderer_init(self):
        """Test ProgressRenderer initialization."""
        renderer = ProgressRenderer()
        assert renderer.MAX_OUTPUT_LINES == 3

    def test_render_returns_panel(self):
        """Test that render returns a Rich Panel."""
        renderer = ProgressRenderer()
        state = ProgressState(phase_name="IMPLEMENTATION")
        phase_progress = Progress()
        phase_task_id = phase_progress.add_task("IMPLEMENTATION", total=100, completed=0)

        context = RenderContext(
            state=state,
            phase_progress=phase_progress,
            tasks_progress=Progress(),
            phase_task_id=phase_task_id,
            tasks_task_id=None,
        )

        result = renderer.render(context)
        assert isinstance(result, Panel)

    def test_render_includes_feature_name(self):
        """Test that render includes feature name when set."""
        renderer = ProgressRenderer()
        state = ProgressState(
            phase_name="IMPLEMENTATION",
            feature_name="my-feature",
        )
        phase_progress = Progress()
        phase_task_id = phase_progress.add_task("IMPLEMENTATION", total=100, completed=0)

        context = RenderContext(
            state=state,
            phase_progress=phase_progress,
            tasks_progress=Progress(),
            phase_task_id=phase_task_id,
            tasks_task_id=None,
        )

        # Render and verify no exceptions
        result = renderer.render(context)
        assert result is not None

    def test_render_with_current_task(self):
        """Test rendering with an active task."""
        renderer = ProgressRenderer()
        state = ProgressState(
            phase_name="IMPLEMENTATION",
            current_task_id="1.5",
            current_task_name="Implement user model",
        )
        phase_progress = Progress()
        phase_task_id = phase_progress.add_task("IMPLEMENTATION", total=100, completed=50)

        context = RenderContext(
            state=state,
            phase_progress=phase_progress,
            tasks_progress=Progress(),
            phase_task_id=phase_task_id,
            tasks_task_id=None,
        )

        result = renderer.render(context)
        assert result is not None

    def test_render_with_activity(self):
        """Test rendering with current activity."""
        renderer = ProgressRenderer()
        activity = Activity(
            type=ActivityType.WRITING_FILE,
            description="Writing user.py",
        )
        state = ProgressState(
            phase_name="IMPLEMENTATION",
            current_activity=activity,
        )
        phase_progress = Progress()
        phase_task_id = phase_progress.add_task("IMPLEMENTATION", total=100, completed=0)

        context = RenderContext(
            state=state,
            phase_progress=phase_progress,
            tasks_progress=Progress(),
            phase_task_id=phase_task_id,
            tasks_task_id=None,
        )

        result = renderer.render(context)
        assert result is not None

    def test_render_with_output_lines(self):
        """Test rendering with output lines."""
        renderer = ProgressRenderer()
        state = ProgressState(
            phase_name="IMPLEMENTATION",
            last_output_lines=["Line 1", "Line 2", "A very long line that should be truncated" * 5],
        )
        phase_progress = Progress()
        phase_task_id = phase_progress.add_task("IMPLEMENTATION", total=100, completed=0)

        context = RenderContext(
            state=state,
            phase_progress=phase_progress,
            tasks_progress=Progress(),
            phase_task_id=phase_task_id,
            tasks_task_id=None,
        )

        result = renderer.render(context)
        assert result is not None

    def test_format_elapsed_static_method(self):
        """Test that format_elapsed works as static method."""
        # Can be called without instance
        result = ProgressRenderer.format_elapsed(3661)
        assert result == "1h01m01s"

    def test_format_timeout_static_method(self):
        """Test that format_timeout works as static method."""
        # Can be called without instance
        result = ProgressRenderer.format_timeout(7200)
        assert result == "2h00m"


class TestNormalizeAgentName:
    """Tests for normalize_agent_name function."""

    def test_normalize_lowercase_with_hyphen(self):
        """Test normalizing already correct format."""
        assert normalize_agent_name("backend-agent") == "backend-agent"

    def test_normalize_uppercase_to_lowercase(self):
        """Test that uppercase is converted to lowercase."""
        assert normalize_agent_name("TDD-agent") == "tdd-agent"
        assert normalize_agent_name("BACKEND-AGENT") == "backend-agent"

    def test_normalize_spaces_to_hyphens(self):
        """Test that spaces are converted to hyphens."""
        assert normalize_agent_name("TDD red agent") == "tdd-red-agent"
        assert normalize_agent_name("my cool agent") == "my-cool-agent"

    def test_normalize_underscores_to_hyphens(self):
        """Test that underscores are converted to hyphens."""
        assert normalize_agent_name("backend_agent") == "backend-agent"
        assert normalize_agent_name("tdd_red_agent") == "tdd-red-agent"

    def test_normalize_adds_agent_suffix(self):
        """Test that -agent suffix is added when missing."""
        assert normalize_agent_name("backend") == "backend-agent"
        assert normalize_agent_name("tdd-red") == "tdd-red-agent"
        assert normalize_agent_name("TDD") == "tdd-agent"

    def test_normalize_handles_agent_without_hyphen(self):
        """Test normalizing 'backendagent' to 'backend-agent'."""
        assert normalize_agent_name("backendagent") == "backend-agent"
        assert normalize_agent_name("tddredagent") == "tddred-agent"

    def test_normalize_removes_duplicate_hyphens(self):
        """Test that duplicate hyphens are collapsed."""
        assert normalize_agent_name("tdd--red--agent") == "tdd-red-agent"
        assert normalize_agent_name("backend---agent") == "backend-agent"

    def test_normalize_strips_leading_trailing(self):
        """Test that leading/trailing whitespace and hyphens are removed."""
        assert normalize_agent_name("  backend-agent  ") == "backend-agent"
        assert normalize_agent_name("-backend-agent-") == "backend-agent"

    def test_normalize_empty_string(self):
        """Test that empty string returns empty."""
        assert normalize_agent_name("") == ""
        assert normalize_agent_name("  ") == ""

    def test_normalize_mixed_case_with_spaces(self):
        """Test real-world example: 'TDD red agent'."""
        assert normalize_agent_name("TDD red agent") == "tdd-red-agent"
        assert normalize_agent_name("Model Agent") == "model-agent"


class TestMatchAgentName:
    """Tests for match_agent_name function."""

    def test_exact_match(self):
        """Test exact match in available agents."""
        available = ["backend-agent", "frontend-agent", "tdd-red-agent"]
        assert match_agent_name("backend-agent", available) == "backend-agent"
        assert match_agent_name("tdd-red-agent", available) == "tdd-red-agent"

    def test_normalized_match(self):
        """Test matching after normalizing available agents."""
        available = ["Backend", "Frontend", "TDD-Red"]
        assert match_agent_name("backend-agent", available) == "Backend"
        assert match_agent_name("tdd-red-agent", available) == "TDD-Red"

    def test_prefix_match(self):
        """Test prefix matching for partial names."""
        available = ["backend-agent", "frontend-agent"]
        # base name "backend" matches "backend-agent"
        assert match_agent_name("backend-agent", available) == "backend-agent"

    def test_no_match_returns_none(self):
        """Test that non-matching agent returns None."""
        available = ["backend-agent", "frontend-agent"]
        assert match_agent_name("nonexistent-agent", available) is None

    def test_empty_available_list(self):
        """Test with empty available agents list."""
        assert match_agent_name("backend-agent", []) is None

    def test_empty_name(self):
        """Test with empty name."""
        available = ["backend-agent"]
        assert match_agent_name("", available) is None

    def test_match_preserves_original_casing(self):
        """Test that matched result preserves original casing from available list."""
        available = ["TDD-Red-Agent", "Backend-Agent"]
        result = match_agent_name("tdd-red-agent", available)
        assert result == "TDD-Red-Agent"


class TestAgentDelegationPatterns:
    """Tests for improved AGENT_DELEGATION pattern detection."""

    def test_detect_delegation_with_spaces(self):
        """Test detection of 'TDD red agent' (with spaces)."""
        parser = OutputParser()
        activity = parser.parse("let me use the TDD red agent to write tests")
        assert activity is not None
        assert activity.type == ActivityType.AGENT_DELEGATION
        # Detail should capture "TDD red agent"
        assert "TDD" in activity.detail or "tdd" in activity.detail.lower()

    def test_detect_delegation_case_insensitive(self):
        """Test case-insensitive matching."""
        parser = OutputParser()
        activity = parser.parse("I'll use the BACKEND-AGENT")
        assert activity is not None
        assert activity.type == ActivityType.AGENT_DELEGATION
        assert activity.detail is not None

    def test_detect_delegation_with_delegate_keyword(self):
        """Test 'delegate to' pattern."""
        parser = OutputParser()
        activity = parser.parse("I'll delegate this to the model-agent")
        assert activity is not None
        assert activity.type == ActivityType.AGENT_DELEGATION

    def test_detect_delegation_invoke(self):
        """Test 'invoke' pattern."""
        parser = OutputParser()
        activity = parser.parse("invoking the backend agent")
        assert activity is not None
        assert activity.type == ActivityType.AGENT_DELEGATION

    def test_detect_subagent_type_json(self):
        """Test JSON stream subagent_type pattern."""
        parser = OutputParser()
        activity = parser.parse('{"subagent_type": "tdd-red"}')
        assert activity is not None
        assert activity.type == ActivityType.AGENT_DELEGATION
        assert "tdd-red" in activity.detail

    def test_detect_let_me_use_pattern(self):
        """Test 'let me use' pattern."""
        parser = OutputParser()
        activity = parser.parse("let me use the backend-agent to handle this")
        assert activity is not None
        assert activity.type == ActivityType.AGENT_DELEGATION

    def test_no_false_positive_for_random_text(self):
        """Test that random text doesn't trigger false positive."""
        parser = OutputParser()
        activity = parser.parse("I'm working on the user interface")
        # Should be THINKING or None, not AGENT_DELEGATION
        if activity:
            assert activity.type != ActivityType.AGENT_DELEGATION


class TestProgressDisplayAgentDelegation:
    """Tests for agent delegation handling in ProgressDisplay."""

    def test_delegation_updates_agent_name(self):
        """Test that delegation updates the displayed agent name."""
        display = ProgressDisplay()
        display.start(
            "IMPLEMENTATION",
            agent_name="dev-agent",
            available_agents=["backend-agent", "frontend-agent", "tdd-red-agent"],
        )

        # Simulate delegation detection
        display.process_output("let me use the backend-agent")

        assert display._state.agent_name == "backend-agent"
        assert display._state.delegated_from == "dev-agent"
        display.stop()

    def test_delegation_with_normalized_name(self):
        """Test delegation with name that needs normalization."""
        display = ProgressDisplay()
        display.start(
            "IMPLEMENTATION",
            agent_name="dev-agent",
            available_agents=["tdd-red-agent"],
        )

        # Use name with spaces that needs normalization
        display.process_output("let me use the TDD red agent")

        assert display._state.agent_name == "tdd-red-agent"
        display.stop()

    def test_delegation_resets_on_task_complete(self):
        """Test that delegation resets when task completes."""
        display = ProgressDisplay()
        display.start(
            "IMPLEMENTATION",
            agent_name="dev-agent",
            available_agents=["backend-agent"],
        )

        # Delegate
        display.process_output("let me use the backend-agent")
        assert display._state.agent_name == "backend-agent"

        # Complete task - should reset
        display.process_output("**Status**: completed")
        assert display._state.agent_name == "dev-agent"
        assert display._state.delegated_from is None
        display.stop()

    def test_delegation_ignored_when_not_in_available_list(self):
        """Test that unknown agents don't update display."""
        display = ProgressDisplay()
        display.start(
            "IMPLEMENTATION",
            agent_name="dev-agent",
            available_agents=["backend-agent"],  # Only backend available
        )

        # Try to delegate to unknown agent
        display.process_output("let me use the mystery-agent")

        # Should not update
        assert display._state.agent_name == "dev-agent"
        assert display._state.delegated_from is None
        display.stop()

    def test_delegation_allowed_when_no_available_list(self):
        """Test that delegation works when available_agents is empty."""
        display = ProgressDisplay()
        display.start(
            "IMPLEMENTATION",
            agent_name="dev-agent",
            available_agents=[],  # No available list
        )

        # Delegate - should work since no restriction
        display.process_output("let me use the backend-agent")

        assert display._state.agent_name == "backend-agent"
        display.stop()
