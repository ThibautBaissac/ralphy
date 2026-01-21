"""Tests pour le module progress."""

from datetime import datetime

import pytest

from ralphy.progress import ActivityType, Activity, OutputParser, ProgressDisplay, ProgressState


class TestActivityType:
    """Tests pour ActivityType enum."""

    def test_activity_values(self):
        """Vérifie les valeurs de l'enum."""
        assert ActivityType.IDLE.value == "idle"
        assert ActivityType.WRITING_FILE.value == "writing_file"
        assert ActivityType.RUNNING_TEST.value == "running_test"
        assert ActivityType.RUNNING_COMMAND.value == "running_command"
        assert ActivityType.TASK_COMPLETE.value == "task_complete"


class TestActivity:
    """Tests pour Activity dataclass."""

    def test_activity_creation(self):
        """Test création d'une activité."""
        activity = Activity(
            type=ActivityType.WRITING_FILE,
            description="Writing app/models/user.rb",
            detail="app/models/user.rb",
        )
        assert activity.type == ActivityType.WRITING_FILE
        assert activity.description == "Writing app/models/user.rb"
        assert activity.detail == "app/models/user.rb"

    def test_activity_without_detail(self):
        """Test activité sans détail."""
        activity = Activity(
            type=ActivityType.RUNNING_TEST,
            description="Running tests",
        )
        assert activity.detail is None


class TestOutputParser:
    """Tests pour OutputParser."""

    def test_detect_writing_file(self):
        """Test détection d'écriture de fichier."""
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
        """Test détection d'exécution de tests."""
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
        """Test détection d'exécution de commande."""
        parser = OutputParser()

        activity = parser.parse("Running: bundle install")
        assert activity is not None
        assert activity.type == ActivityType.RUNNING_COMMAND

        activity = parser.parse("$ git status")
        assert activity is not None
        assert activity.type == ActivityType.RUNNING_COMMAND

    def test_detect_task_complete(self):
        """Test détection de tâche complétée."""
        parser = OutputParser()

        activity = parser.parse("**Statut**: completed")
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

    def test_process_output_increments_tasks_on_completion(self):
        """Test que les tâches sont incrémentées quand une est complétée."""
        display = ProgressDisplay()
        display.start("IMPLEMENTATION", 10)

        initial_completed = display._state.tasks_completed
        display.process_output("**Statut**: completed")
        assert display._state.tasks_completed == initial_completed + 1

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
    """Tests pour les fonctions de formatage du temps."""

    def test_format_elapsed_seconds_only(self):
        """Test formatage pour moins d'une minute."""
        display = ProgressDisplay()
        assert display._format_elapsed(45) == "00:45"
        assert display._format_elapsed(0) == "00:00"
        assert display._format_elapsed(59) == "00:59"

    def test_format_elapsed_minutes_and_seconds(self):
        """Test formatage avec minutes et secondes."""
        display = ProgressDisplay()
        assert display._format_elapsed(65) == "01:05"
        assert display._format_elapsed(130) == "02:10"
        assert display._format_elapsed(3599) == "59:59"

    def test_format_elapsed_hours(self):
        """Test formatage avec heures."""
        display = ProgressDisplay()
        assert display._format_elapsed(3600) == "1h00m00s"
        assert display._format_elapsed(3661) == "1h01m01s"
        assert display._format_elapsed(7325) == "2h02m05s"

    def test_format_timeout_minutes_only(self):
        """Test formatage timeout en minutes."""
        display = ProgressDisplay()
        assert display._format_timeout(1800) == "30m"
        assert display._format_timeout(600) == "10m"
        assert display._format_timeout(60) == "1m"

    def test_format_timeout_hours(self):
        """Test formatage timeout en heures."""
        display = ProgressDisplay()
        assert display._format_timeout(3600) == "1h00m"
        assert display._format_timeout(7200) == "2h00m"
        assert display._format_timeout(14400) == "4h00m"
        assert display._format_timeout(5400) == "1h30m"


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
