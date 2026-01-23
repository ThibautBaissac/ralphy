"""Tests for the journal module."""

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from ralphy.journal import (
    EventType,
    JournalEvent,
    JournalWriter,
    PhaseSummary,
    WorkflowJournal,
    WorkflowSummary,
    _now_iso,
)
from ralphy.progress import Activity, ActivityType


class TestEventType:
    """Tests pour EventType enum."""

    def test_event_type_values(self):
        """Vérifie les valeurs de l'enum."""
        assert EventType.WORKFLOW_START.value == "workflow_start"
        assert EventType.WORKFLOW_END.value == "workflow_end"
        assert EventType.PHASE_START.value == "phase_start"
        assert EventType.PHASE_END.value == "phase_end"
        assert EventType.TASK_START.value == "task_start"
        assert EventType.TASK_COMPLETE.value == "task_complete"
        assert EventType.ACTIVITY.value == "activity"
        assert EventType.TOKEN_UPDATE.value == "token_update"
        assert EventType.CIRCUIT_BREAKER.value == "circuit_breaker"
        assert EventType.VALIDATION.value == "validation"
        assert EventType.ERROR.value == "error"


class TestJournalEvent:
    """Tests pour JournalEvent dataclass."""

    def test_event_creation(self):
        """Test création d'un événement."""
        event = JournalEvent(
            timestamp="2026-01-22T10:00:00+00:00",
            event_type=EventType.WORKFLOW_START,
            phase=None,
            data={"feature": "test-feature"},
        )
        assert event.timestamp == "2026-01-22T10:00:00+00:00"
        assert event.event_type == EventType.WORKFLOW_START
        assert event.phase is None
        assert event.data == {"feature": "test-feature"}

    def test_event_to_dict(self):
        """Test conversion en dictionnaire."""
        event = JournalEvent(
            timestamp="2026-01-22T10:00:00+00:00",
            event_type=EventType.PHASE_START,
            phase="SPECIFICATION",
            data={"model": "sonnet", "timeout": 1800},
        )
        d = event.to_dict()
        assert d["timestamp"] == "2026-01-22T10:00:00+00:00"
        assert d["event_type"] == "phase_start"
        assert d["phase"] == "SPECIFICATION"
        assert d["data"] == {"model": "sonnet", "timeout": 1800}

    def test_event_from_dict(self):
        """Test création depuis un dictionnaire."""
        d = {
            "timestamp": "2026-01-22T10:00:00+00:00",
            "event_type": "task_complete",
            "phase": "IMPLEMENTATION",
            "data": {"task_id": "1.2", "task_name": "Create model"},
        }
        event = JournalEvent.from_dict(d)
        assert event.timestamp == "2026-01-22T10:00:00+00:00"
        assert event.event_type == EventType.TASK_COMPLETE
        assert event.phase == "IMPLEMENTATION"
        assert event.data == {"task_id": "1.2", "task_name": "Create model"}

    def test_event_roundtrip(self):
        """Test conversion aller-retour dict -> event -> dict."""
        original = JournalEvent(
            timestamp="2026-01-22T10:00:00+00:00",
            event_type=EventType.TOKEN_UPDATE,
            phase="QA",
            data={"input_tokens": 1000, "output_tokens": 500},
        )
        d = original.to_dict()
        restored = JournalEvent.from_dict(d)
        assert restored.timestamp == original.timestamp
        assert restored.event_type == original.event_type
        assert restored.phase == original.phase
        assert restored.data == original.data


class TestPhaseSummary:
    """Tests pour PhaseSummary dataclass."""

    def test_phase_summary_creation(self):
        """Test création d'un résumé de phase."""
        summary = PhaseSummary(
            phase_name="SPECIFICATION",
            model="sonnet",
            timeout=1800,
            started_at="2026-01-22T10:00:00+00:00",
        )
        assert summary.phase_name == "SPECIFICATION"
        assert summary.model == "sonnet"
        assert summary.timeout == 1800
        assert summary.ended_at is None
        assert summary.outcome == "unknown"

    def test_phase_summary_to_dict(self):
        """Test conversion en dictionnaire."""
        summary = PhaseSummary(
            phase_name="IMPLEMENTATION",
            model="opus",
            timeout=14400,
            started_at="2026-01-22T10:00:00+00:00",
            ended_at="2026-01-22T12:00:00+00:00",
            duration_seconds=7200.0,
            outcome="success",
            tasks_total=10,
            tasks_completed=10,
            cost_usd=2.50,
        )
        d = summary.to_dict()
        assert d["phase_name"] == "IMPLEMENTATION"
        assert d["model"] == "opus"
        assert d["outcome"] == "success"
        assert d["tasks_completed"] == 10
        assert d["cost_usd"] == 2.50


class TestWorkflowSummary:
    """Tests pour WorkflowSummary dataclass."""

    def test_workflow_summary_creation(self):
        """Test création d'un résumé de workflow."""
        summary = WorkflowSummary(
            feature_name="test-feature",
            started_at="2026-01-22T10:00:00+00:00",
        )
        assert summary.feature_name == "test-feature"
        assert summary.ended_at is None
        assert summary.outcome == "unknown"
        assert summary.phases == []

    def test_workflow_summary_to_dict(self):
        """Test conversion en dictionnaire avec phases."""
        phase1 = PhaseSummary(
            phase_name="SPECIFICATION",
            model="sonnet",
            timeout=1800,
            started_at="2026-01-22T10:00:00+00:00",
            ended_at="2026-01-22T10:10:00+00:00",
            duration_seconds=600.0,
            outcome="success",
            cost_usd=0.50,
        )
        phase2 = PhaseSummary(
            phase_name="IMPLEMENTATION",
            model="opus",
            timeout=14400,
            started_at="2026-01-22T10:15:00+00:00",
            ended_at="2026-01-22T12:15:00+00:00",
            duration_seconds=7200.0,
            outcome="success",
            tasks_total=10,
            tasks_completed=10,
            cost_usd=3.00,
        )
        summary = WorkflowSummary(
            feature_name="test-feature",
            started_at="2026-01-22T10:00:00+00:00",
            ended_at="2026-01-22T14:00:00+00:00",
            total_duration_seconds=14400.0,
            outcome="completed",
            phases=[phase1, phase2],
            total_cost_usd=3.50,
            total_tasks_completed=10,
            total_tasks_total=10,
        )
        d = summary.to_dict()
        assert d["feature_name"] == "test-feature"
        assert d["outcome"] == "completed"
        assert len(d["phases"]) == 2
        assert d["phases"][0]["phase_name"] == "SPECIFICATION"
        assert d["phases"][1]["phase_name"] == "IMPLEMENTATION"
        assert d["total_cost_usd"] == 3.50


class TestNowIso:
    """Tests pour la fonction _now_iso."""

    def test_now_iso_format(self):
        """Test que _now_iso retourne un format ISO 8601 valide."""
        timestamp = _now_iso()
        # Should be parseable
        dt = datetime.fromisoformat(timestamp)
        assert dt.tzinfo is not None  # Has timezone


class TestWorkflowJournal:
    """Tests pour WorkflowJournal."""

    @pytest.fixture
    def temp_feature_dir(self, tmp_path):
        """Crée un répertoire feature temporaire."""
        feature_dir = tmp_path / "docs" / "features" / "test-feature"
        feature_dir.mkdir(parents=True)
        return feature_dir

    @pytest.fixture
    def journal(self, temp_feature_dir):
        """Crée une instance de journal pour les tests."""
        return WorkflowJournal(temp_feature_dir, "test-feature")

    def test_journal_initialization(self, journal, temp_feature_dir):
        """Test initialisation du journal."""
        assert journal.feature_dir == temp_feature_dir
        assert journal.feature_name == "test-feature"
        assert not journal.is_started

    def test_start_workflow(self, journal, temp_feature_dir):
        """Test démarrage du workflow."""
        journal.start_workflow()
        assert journal.is_started

        # Vérifie que le fichier JSONL existe
        jsonl_path = temp_feature_dir / ".ralphy" / "progress.jsonl"
        assert jsonl_path.exists()

        # Vérifie le contenu
        with open(jsonl_path) as f:
            line = f.readline()
            event = json.loads(line)
            assert event["event_type"] == "workflow_start"
            assert event["data"]["feature"] == "test-feature"

    def test_start_workflow_fresh(self, journal, temp_feature_dir):
        """Test démarrage fresh qui efface le journal précédent."""
        # Crée un journal existant
        ralphy_dir = temp_feature_dir / ".ralphy"
        ralphy_dir.mkdir(parents=True, exist_ok=True)
        jsonl_path = ralphy_dir / "progress.jsonl"
        jsonl_path.write_text('{"old": "data"}\n')

        journal.start_workflow(fresh=True)

        # Vérifie que l'ancien contenu a été effacé
        with open(jsonl_path) as f:
            content = f.read()
            assert "old" not in content
            assert "workflow_start" in content

    def test_start_workflow_idempotent(self, journal, temp_feature_dir):
        """Test que start_workflow ne fait rien si déjà démarré."""
        journal.start_workflow()
        journal.start_workflow()  # Should not add another event

        jsonl_path = temp_feature_dir / ".ralphy" / "progress.jsonl"
        with open(jsonl_path) as f:
            lines = f.readlines()
            assert len(lines) == 1  # Only one start event

    def test_end_workflow(self, journal, temp_feature_dir):
        """Test fin du workflow."""
        journal.start_workflow()
        journal.end_workflow("completed")

        # Vérifie le fichier JSONL
        jsonl_path = temp_feature_dir / ".ralphy" / "progress.jsonl"
        with open(jsonl_path) as f:
            lines = f.readlines()
            assert len(lines) == 2
            end_event = json.loads(lines[1])
            assert end_event["event_type"] == "workflow_end"
            assert end_event["data"]["outcome"] == "completed"

        # Vérifie le fichier summary
        summary_path = temp_feature_dir / ".ralphy" / "progress_summary.json"
        assert summary_path.exists()
        with open(summary_path) as f:
            summary = json.load(f)
            assert summary["feature_name"] == "test-feature"
            assert summary["outcome"] == "completed"

    def test_end_workflow_without_start(self, journal, temp_feature_dir):
        """Test que end_workflow ne fait rien si pas démarré."""
        journal.end_workflow("completed")

        jsonl_path = temp_feature_dir / ".ralphy" / "progress.jsonl"
        assert not jsonl_path.exists()

    def test_start_phase(self, journal, temp_feature_dir):
        """Test démarrage d'une phase."""
        journal.start_workflow()
        journal.start_phase("SPECIFICATION", model="sonnet", timeout=1800, tasks_total=5)

        jsonl_path = temp_feature_dir / ".ralphy" / "progress.jsonl"
        with open(jsonl_path) as f:
            lines = f.readlines()
            assert len(lines) == 2
            phase_event = json.loads(lines[1])
            assert phase_event["event_type"] == "phase_start"
            assert phase_event["phase"] == "SPECIFICATION"
            assert phase_event["data"]["model"] == "sonnet"
            assert phase_event["data"]["timeout"] == 1800

    def test_end_phase(self, journal, temp_feature_dir):
        """Test fin d'une phase."""
        journal.start_workflow()
        journal.start_phase("SPECIFICATION", model="sonnet", timeout=1800)
        journal.end_phase(
            outcome="success",
            token_usage={"input_tokens": 1000},
            cost=0.50,
            tasks_completed=3,
        )

        jsonl_path = temp_feature_dir / ".ralphy" / "progress.jsonl"
        with open(jsonl_path) as f:
            lines = f.readlines()
            assert len(lines) == 3
            end_event = json.loads(lines[2])
            assert end_event["event_type"] == "phase_end"
            assert end_event["data"]["outcome"] == "success"
            assert end_event["data"]["cost_usd"] == 0.50

    def test_record_task_event_start(self, journal, temp_feature_dir):
        """Test enregistrement d'un événement task start."""
        journal.start_workflow()
        journal.start_phase("IMPLEMENTATION")
        journal.record_task_event("start", "1.2", "Create user model")

        jsonl_path = temp_feature_dir / ".ralphy" / "progress.jsonl"
        with open(jsonl_path) as f:
            lines = f.readlines()
            task_event = json.loads(lines[-1])
            assert task_event["event_type"] == "task_start"
            assert task_event["data"]["task_id"] == "1.2"
            assert task_event["data"]["task_name"] == "Create user model"

    def test_record_task_event_complete(self, journal, temp_feature_dir):
        """Test enregistrement d'un événement task complete."""
        journal.start_workflow()
        journal.start_phase("IMPLEMENTATION")
        journal.record_task_event("complete", "1.2", "Create user model")

        jsonl_path = temp_feature_dir / ".ralphy" / "progress.jsonl"
        with open(jsonl_path) as f:
            lines = f.readlines()
            task_event = json.loads(lines[-1])
            assert task_event["event_type"] == "task_complete"

    def test_record_activity(self, journal, temp_feature_dir):
        """Test enregistrement d'une activité."""
        journal.start_workflow()
        journal.start_phase("IMPLEMENTATION")

        activity = Activity(
            type=ActivityType.WRITING_FILE,
            description="Writing app/models/user.rb",
            detail="app/models/user.rb",
        )
        journal.record_activity(activity)

        jsonl_path = temp_feature_dir / ".ralphy" / "progress.jsonl"
        with open(jsonl_path) as f:
            lines = f.readlines()
            activity_event = json.loads(lines[-1])
            assert activity_event["event_type"] == "activity"
            assert activity_event["data"]["type"] == "writing_file"
            assert activity_event["data"]["detail"] == "app/models/user.rb"

    def test_record_token_update(self, journal, temp_feature_dir):
        """Test enregistrement d'une mise à jour de tokens."""
        journal.start_workflow()
        journal.start_phase("SPECIFICATION")

        # Create mock TokenUsage
        usage = MagicMock()
        usage.input_tokens = 1500
        usage.output_tokens = 500
        usage.cache_read_tokens = 100
        usage.cache_creation_tokens = 50
        usage.total_tokens = 2150
        usage.context_utilization = 1.075

        journal.record_token_update(usage, 0.05)

        jsonl_path = temp_feature_dir / ".ralphy" / "progress.jsonl"
        with open(jsonl_path) as f:
            lines = f.readlines()
            token_event = json.loads(lines[-1])
            assert token_event["event_type"] == "token_update"
            assert token_event["data"]["input_tokens"] == 1500
            assert token_event["data"]["output_tokens"] == 500
            assert token_event["data"]["cost_usd"] == 0.05

    def test_record_circuit_breaker(self, journal, temp_feature_dir):
        """Test enregistrement d'un événement circuit breaker."""
        journal.start_workflow()
        journal.start_phase("IMPLEMENTATION")
        journal.record_circuit_breaker("INACTIVITY", attempts=2, is_open=False)

        jsonl_path = temp_feature_dir / ".ralphy" / "progress.jsonl"
        with open(jsonl_path) as f:
            lines = f.readlines()
            cb_event = json.loads(lines[-1])
            assert cb_event["event_type"] == "circuit_breaker"
            assert cb_event["data"]["trigger_type"] == "INACTIVITY"
            assert cb_event["data"]["attempts"] == 2
            assert cb_event["data"]["is_open"] is False

    def test_record_validation(self, journal, temp_feature_dir):
        """Test enregistrement d'une validation."""
        journal.start_workflow()
        journal.record_validation("SPECIFICATION", approved=True, feedback="Looks good")

        jsonl_path = temp_feature_dir / ".ralphy" / "progress.jsonl"
        with open(jsonl_path) as f:
            lines = f.readlines()
            val_event = json.loads(lines[-1])
            assert val_event["event_type"] == "validation"
            assert val_event["phase"] == "SPECIFICATION"
            assert val_event["data"]["approved"] is True
            assert val_event["data"]["feedback"] == "Looks good"

    def test_record_error(self, journal, temp_feature_dir):
        """Test enregistrement d'une erreur."""
        journal.start_workflow()
        journal.start_phase("IMPLEMENTATION")
        journal.record_error("Connection timeout", "timeout")

        jsonl_path = temp_feature_dir / ".ralphy" / "progress.jsonl"
        with open(jsonl_path) as f:
            lines = f.readlines()
            error_event = json.loads(lines[-1])
            assert error_event["event_type"] == "error"
            assert error_event["data"]["error_type"] == "timeout"
            assert error_event["data"]["message"] == "Connection timeout"

    def test_full_workflow_lifecycle(self, journal, temp_feature_dir):
        """Test cycle de vie complet d'un workflow."""
        # Start workflow
        journal.start_workflow()

        # Phase 1: SPECIFICATION
        journal.start_phase("SPECIFICATION", model="sonnet", timeout=1800)
        journal.end_phase("success", cost=0.50)

        # Validation
        journal.record_validation("SPECIFICATION", approved=True)

        # Phase 2: IMPLEMENTATION
        journal.start_phase("IMPLEMENTATION", model="opus", timeout=14400, tasks_total=5)
        journal.record_task_event("start", "1.1", "Setup")
        journal.record_task_event("complete", "1.1", "Setup")
        journal.end_phase("success", cost=2.00, tasks_completed=5)

        # Phase 3: QA
        journal.start_phase("QA", model="sonnet", timeout=1800)
        journal.end_phase("success", cost=0.30)

        # Validation
        journal.record_validation("QA", approved=True)

        # Phase 4: PR
        journal.start_phase("PR", model="haiku", timeout=600)
        journal.end_phase("success", cost=0.10)

        # End workflow
        journal.end_workflow("completed")

        # Verify summary
        summary_path = temp_feature_dir / ".ralphy" / "progress_summary.json"
        with open(summary_path) as f:
            summary = json.load(f)
            assert summary["outcome"] == "completed"
            assert len(summary["phases"]) == 4
            assert summary["total_cost_usd"] == pytest.approx(2.90, rel=0.01)


class TestWorkflowJournalThreadSafety:
    """Tests pour la thread safety du journal."""

    @pytest.fixture
    def temp_feature_dir(self, tmp_path):
        """Crée un répertoire feature temporaire."""
        feature_dir = tmp_path / "docs" / "features" / "test-feature"
        feature_dir.mkdir(parents=True)
        return feature_dir

    def test_concurrent_writes(self, temp_feature_dir):
        """Test écritures concurrentes."""
        journal = WorkflowJournal(temp_feature_dir, "test-feature")
        journal.start_workflow()
        journal.start_phase("IMPLEMENTATION", tasks_total=100)

        errors = []
        event_count = 100

        def write_events(thread_id):
            try:
                for i in range(event_count // 10):
                    journal.record_task_event("start", f"{thread_id}.{i}")
                    journal.record_task_event("complete", f"{thread_id}.{i}")
            except Exception as e:
                errors.append(e)

        # Lancer 10 threads qui écrivent en parallèle
        threads = []
        for i in range(10):
            t = threading.Thread(target=write_events, args=(i,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        assert len(errors) == 0, f"Errors during concurrent writes: {errors}"

        # Vérifier que tous les événements ont été écrits
        jsonl_path = temp_feature_dir / ".ralphy" / "progress.jsonl"
        with open(jsonl_path) as f:
            lines = f.readlines()
            # 1 workflow_start + 1 phase_start + 200 task events = 202
            # (10 threads × 10 iterations × 2 events each = 200)
            assert len(lines) == 202

    def test_concurrent_read_write(self, temp_feature_dir):
        """Test lecture/écriture concurrentes."""
        journal = WorkflowJournal(temp_feature_dir, "test-feature")
        journal.start_workflow()

        errors = []
        stop_flag = threading.Event()

        def writer():
            try:
                for i in range(50):
                    if stop_flag.is_set():
                        break
                    journal.record_task_event("start", f"task-{i}")
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for _ in range(50):
                    if stop_flag.is_set():
                        break
                    _ = journal.is_started
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        writer_thread = threading.Thread(target=writer)
        reader_thread = threading.Thread(target=reader)

        writer_thread.start()
        reader_thread.start()

        writer_thread.join(timeout=5)
        reader_thread.join(timeout=5)
        stop_flag.set()

        assert len(errors) == 0, f"Errors during concurrent read/write: {errors}"


class TestWorkflowJournalInterruptionRecovery:
    """Tests pour la récupération après interruption."""

    @pytest.fixture
    def temp_feature_dir(self, tmp_path):
        """Crée un répertoire feature temporaire."""
        feature_dir = tmp_path / "docs" / "features" / "test-feature"
        feature_dir.mkdir(parents=True)
        return feature_dir

    def test_partial_journal_readable(self, temp_feature_dir):
        """Test que un journal partiel (interrompu) est lisible."""
        journal = WorkflowJournal(temp_feature_dir, "test-feature")
        journal.start_workflow()
        journal.start_phase("IMPLEMENTATION")
        journal.record_task_event("start", "1.1")
        # Simulate interruption - no end_phase or end_workflow

        # Verify the partial journal is still valid JSON lines
        jsonl_path = temp_feature_dir / ".ralphy" / "progress.jsonl"
        with open(jsonl_path) as f:
            for line in f:
                # Should not raise
                event = json.loads(line)
                assert "timestamp" in event
                assert "event_type" in event

    def test_resume_workflow_preserves_history(self, temp_feature_dir):
        """Test que reprendre un workflow préserve l'historique."""
        # First run - interrupted
        journal1 = WorkflowJournal(temp_feature_dir, "test-feature")
        journal1.start_workflow()
        journal1.start_phase("SPECIFICATION")
        journal1.end_phase("success")

        # Second run - resume (not fresh)
        journal2 = WorkflowJournal(temp_feature_dir, "test-feature")
        journal2.start_workflow(fresh=False)  # Should append
        journal2.start_phase("IMPLEMENTATION")
        journal2.end_phase("success")
        journal2.end_workflow("completed")

        # Verify both runs are in the journal
        jsonl_path = temp_feature_dir / ".ralphy" / "progress.jsonl"
        with open(jsonl_path) as f:
            lines = f.readlines()
            event_types = [json.loads(line)["event_type"] for line in lines]
            # Count workflow_start events
            start_count = event_types.count("workflow_start")
            assert start_count == 2  # Both runs recorded

    def test_fresh_start_clears_history(self, temp_feature_dir):
        """Test que fresh=True efface l'historique précédent."""
        # First run
        journal1 = WorkflowJournal(temp_feature_dir, "test-feature")
        journal1.start_workflow()
        journal1.start_phase("SPECIFICATION")
        journal1.end_phase("success")

        # Second run - fresh start
        journal2 = WorkflowJournal(temp_feature_dir, "test-feature")
        journal2.start_workflow(fresh=True)  # Should clear and start fresh
        journal2.end_workflow("completed")

        # Verify only second run is in the journal
        jsonl_path = temp_feature_dir / ".ralphy" / "progress.jsonl"
        with open(jsonl_path) as f:
            lines = f.readlines()
            event_types = [json.loads(line)["event_type"] for line in lines]
            # Only one workflow_start (from fresh start)
            start_count = event_types.count("workflow_start")
            assert start_count == 1


class TestJournalWriter:
    """Tests for JournalWriter class."""

    @pytest.fixture
    def temp_paths(self, tmp_path):
        """Create temporary journal paths."""
        journal_path = tmp_path / ".ralphy" / "progress.jsonl"
        summary_path = tmp_path / ".ralphy" / "progress_summary.json"
        return journal_path, summary_path

    def test_writer_initialization(self, temp_paths):
        """Test JournalWriter initialization."""
        journal_path, summary_path = temp_paths
        writer = JournalWriter(journal_path, summary_path)
        assert writer._journal_path == journal_path
        assert writer._summary_path == summary_path

    def test_append_event_creates_directory(self, temp_paths):
        """Test that append_event creates parent directory."""
        journal_path, summary_path = temp_paths
        writer = JournalWriter(journal_path, summary_path)

        event = JournalEvent(
            timestamp="2026-01-22T10:00:00+00:00",
            event_type=EventType.WORKFLOW_START,
            phase=None,
            data={"feature": "test"},
        )
        writer.append_event(event)

        assert journal_path.exists()
        with open(journal_path) as f:
            line = f.readline()
            data = json.loads(line)
            assert data["event_type"] == "workflow_start"

    def test_append_event_appends(self, temp_paths):
        """Test that append_event appends to existing file."""
        journal_path, summary_path = temp_paths
        writer = JournalWriter(journal_path, summary_path)

        event1 = JournalEvent(
            timestamp="2026-01-22T10:00:00+00:00",
            event_type=EventType.WORKFLOW_START,
            phase=None,
            data={},
        )
        event2 = JournalEvent(
            timestamp="2026-01-22T10:01:00+00:00",
            event_type=EventType.PHASE_START,
            phase="SPECIFICATION",
            data={},
        )

        writer.append_event(event1)
        writer.append_event(event2)

        with open(journal_path) as f:
            lines = f.readlines()
            assert len(lines) == 2
            assert json.loads(lines[0])["event_type"] == "workflow_start"
            assert json.loads(lines[1])["event_type"] == "phase_start"

    def test_clear_journal(self, temp_paths):
        """Test that clear_journal removes the file."""
        journal_path, summary_path = temp_paths
        writer = JournalWriter(journal_path, summary_path)

        # Create journal with some content
        event = JournalEvent(
            timestamp="2026-01-22T10:00:00+00:00",
            event_type=EventType.WORKFLOW_START,
            phase=None,
            data={},
        )
        writer.append_event(event)
        assert journal_path.exists()

        # Clear it
        writer.clear_journal()
        assert not journal_path.exists()

    def test_clear_journal_nonexistent(self, temp_paths):
        """Test that clear_journal handles nonexistent file."""
        journal_path, summary_path = temp_paths
        writer = JournalWriter(journal_path, summary_path)

        # Should not raise
        writer.clear_journal()
        assert not journal_path.exists()

    def test_write_summary(self, temp_paths):
        """Test writing workflow summary."""
        journal_path, summary_path = temp_paths
        writer = JournalWriter(journal_path, summary_path)

        summary = WorkflowSummary(
            feature_name="test-feature",
            started_at="2026-01-22T10:00:00+00:00",
            ended_at="2026-01-22T11:00:00+00:00",
            total_duration_seconds=3600.0,
            outcome="completed",
            total_cost_usd=1.50,
        )
        writer.write_summary(summary)

        assert summary_path.exists()
        with open(summary_path) as f:
            data = json.load(f)
            assert data["feature_name"] == "test-feature"
            assert data["outcome"] == "completed"
            assert data["total_cost_usd"] == 1.50

    def test_write_summary_creates_directory(self, temp_paths):
        """Test that write_summary creates parent directory."""
        journal_path, summary_path = temp_paths
        writer = JournalWriter(journal_path, summary_path)

        summary = WorkflowSummary(
            feature_name="test",
            started_at="2026-01-22T10:00:00+00:00",
        )
        writer.write_summary(summary)

        assert summary_path.parent.exists()
        assert summary_path.exists()


class TestCreateEventHelper:
    """Tests for the _create_event helper method."""

    @pytest.fixture
    def journal(self, tmp_path):
        """Create a journal instance for testing."""
        feature_dir = tmp_path / "test-feature"
        feature_dir.mkdir()
        return WorkflowJournal(feature_dir, "test-feature")

    def test_create_event_basic(self, journal):
        """Test basic event creation."""
        journal.start_workflow()
        journal._current_phase_name = "IMPLEMENTATION"

        event = journal._create_event(EventType.TASK_START, task_id="1.1")

        assert event.event_type == EventType.TASK_START
        assert event.phase == "IMPLEMENTATION"
        assert event.data["task_id"] == "1.1"
        # Verify timestamp is a valid ISO format
        assert event.timestamp is not None
        datetime.fromisoformat(event.timestamp)  # Should not raise

    def test_create_event_with_explicit_phase(self, journal):
        """Test event creation with explicit phase."""
        journal.start_workflow()
        journal._current_phase_name = "IMPLEMENTATION"

        event = journal._create_event(
            EventType.VALIDATION,
            phase="SPECIFICATION",
            approved=True,
        )

        assert event.phase == "SPECIFICATION"
        assert event.data["approved"] is True

    def test_create_event_multiple_data_fields(self, journal):
        """Test event creation with multiple data fields."""
        journal.start_workflow()

        event = journal._create_event(
            EventType.TOKEN_UPDATE,
            input_tokens=1000,
            output_tokens=500,
            cost_usd=0.05,
        )

        assert event.data["input_tokens"] == 1000
        assert event.data["output_tokens"] == 500
        assert event.data["cost_usd"] == 0.05

    def test_create_event_uses_current_phase(self, journal):
        """Test that _create_event uses current phase when not specified."""
        journal.start_workflow()
        journal.start_phase("QA")

        event = journal._create_event(EventType.ERROR, message="Test error")

        assert event.phase == "QA"

    def test_create_event_without_phase(self, journal):
        """Test event creation when no phase is active."""
        journal.start_workflow()

        event = journal._create_event(EventType.WORKFLOW_END, outcome="completed")

        assert event.phase is None
        assert event.data["outcome"] == "completed"


class TestAgentDelegationJournal:
    """Tests for agent delegation tracking in the journal."""

    @pytest.fixture
    def temp_feature_dir(self, tmp_path):
        """Create a temporary feature directory."""
        feature_dir = tmp_path / "docs" / "features" / "test-feature"
        feature_dir.mkdir(parents=True)
        return feature_dir

    @pytest.fixture
    def journal(self, temp_feature_dir):
        """Create a journal instance for testing."""
        return WorkflowJournal(temp_feature_dir, "test-feature")

    def test_event_type_includes_agent_delegation(self):
        """Test that AGENT_DELEGATION is in EventType enum."""
        assert EventType.AGENT_DELEGATION.value == "agent_delegation"

    def test_record_agent_delegation(self, journal, temp_feature_dir):
        """Test recording an agent delegation event."""
        journal.start_workflow()
        journal.start_phase("IMPLEMENTATION")
        journal.record_agent_delegation(
            from_agent="dev-agent",
            to_agent="tdd-red-agent",
            task_id="1.5",
        )

        jsonl_path = temp_feature_dir / ".ralphy" / "progress.jsonl"
        with open(jsonl_path) as f:
            lines = f.readlines()
            delegation_event = json.loads(lines[-1])
            assert delegation_event["event_type"] == "agent_delegation"
            assert delegation_event["data"]["from_agent"] == "dev-agent"
            assert delegation_event["data"]["to_agent"] == "tdd-red-agent"
            assert delegation_event["data"]["task_id"] == "1.5"

    def test_record_agent_delegation_without_task_id(self, journal, temp_feature_dir):
        """Test recording delegation without task_id."""
        journal.start_workflow()
        journal.start_phase("IMPLEMENTATION")
        journal.record_agent_delegation(
            from_agent="dev-agent",
            to_agent="backend-agent",
        )

        jsonl_path = temp_feature_dir / ".ralphy" / "progress.jsonl"
        with open(jsonl_path) as f:
            lines = f.readlines()
            delegation_event = json.loads(lines[-1])
            assert delegation_event["data"]["task_id"] is None

    def test_agents_used_tracked_in_phase(self, journal, temp_feature_dir):
        """Test that delegated agents are tracked in phase summary."""
        journal.start_workflow()
        journal.start_phase("IMPLEMENTATION")

        # Record multiple delegations
        journal.record_agent_delegation("dev-agent", "tdd-red-agent")
        journal.record_agent_delegation("dev-agent", "backend-agent")
        journal.record_agent_delegation("dev-agent", "tdd-red-agent")  # Duplicate

        journal.end_phase("success")
        journal.end_workflow("completed")

        summary_path = temp_feature_dir / ".ralphy" / "progress_summary.json"
        with open(summary_path) as f:
            summary = json.load(f)
            impl_phase = summary["phases"][0]
            # Should have unique agents only
            assert impl_phase["agents_used"] == ["tdd-red-agent", "backend-agent"]

    def test_all_agents_used_aggregated_in_summary(self, journal, temp_feature_dir):
        """Test that all_agents_used aggregates from all phases."""
        journal.start_workflow()

        # Phase 1: SPECIFICATION - no delegations
        journal.start_phase("SPECIFICATION")
        journal.end_phase("success")

        # Phase 2: IMPLEMENTATION - some delegations
        journal.start_phase("IMPLEMENTATION")
        journal.record_agent_delegation("dev-agent", "tdd-red-agent")
        journal.record_agent_delegation("dev-agent", "backend-agent")
        journal.end_phase("success")

        # Phase 3: QA - different delegation
        journal.start_phase("QA")
        journal.record_agent_delegation("qa-agent", "security-agent")
        journal.end_phase("success")

        journal.end_workflow("completed")

        summary_path = temp_feature_dir / ".ralphy" / "progress_summary.json"
        with open(summary_path) as f:
            summary = json.load(f)
            # all_agents_used should have all unique agents from all phases
            assert "tdd-red-agent" in summary["all_agents_used"]
            assert "backend-agent" in summary["all_agents_used"]
            assert "security-agent" in summary["all_agents_used"]
            assert len(summary["all_agents_used"]) == 3

    def test_phase_summary_includes_agents_used_field(self, journal, temp_feature_dir):
        """Test that PhaseSummary to_dict includes agents_used."""
        journal.start_workflow()
        journal.start_phase("IMPLEMENTATION")
        journal.record_agent_delegation("dev-agent", "backend-agent")
        journal.end_phase("success")
        journal.end_workflow("completed")

        summary_path = temp_feature_dir / ".ralphy" / "progress_summary.json"
        with open(summary_path) as f:
            summary = json.load(f)
            impl_phase = summary["phases"][0]
            assert "agents_used" in impl_phase
            assert impl_phase["agents_used"] == ["backend-agent"]

    def test_workflow_summary_includes_all_agents_used_field(self, journal, temp_feature_dir):
        """Test that WorkflowSummary to_dict includes all_agents_used."""
        journal.start_workflow()
        journal.start_phase("IMPLEMENTATION")
        journal.end_phase("success")
        journal.end_workflow("completed")

        summary_path = temp_feature_dir / ".ralphy" / "progress_summary.json"
        with open(summary_path) as f:
            summary = json.load(f)
            assert "all_agents_used" in summary
            assert isinstance(summary["all_agents_used"], list)

    def test_record_delegation_not_started(self, journal, temp_feature_dir):
        """Test that delegation is not recorded if workflow not started."""
        journal.record_agent_delegation("dev-agent", "backend-agent")

        jsonl_path = temp_feature_dir / ".ralphy" / "progress.jsonl"
        assert not jsonl_path.exists()

    def test_delegation_without_phase(self, journal, temp_feature_dir):
        """Test recording delegation without active phase."""
        journal.start_workflow()
        # No start_phase called
        journal.record_agent_delegation("dev-agent", "backend-agent")

        jsonl_path = temp_feature_dir / ".ralphy" / "progress.jsonl"
        with open(jsonl_path) as f:
            lines = f.readlines()
            # Should still record the event
            assert len(lines) == 2  # workflow_start + delegation
            delegation_event = json.loads(lines[-1])
            assert delegation_event["event_type"] == "agent_delegation"


class TestPhaseSummaryAgentsUsed:
    """Tests for agents_used field in PhaseSummary dataclass."""

    def test_phase_summary_default_agents_used(self):
        """Test that agents_used defaults to empty list."""
        summary = PhaseSummary(
            phase_name="IMPLEMENTATION",
            model="opus",
            timeout=14400,
            started_at="2026-01-22T10:00:00+00:00",
        )
        assert summary.agents_used == []

    def test_phase_summary_with_agents_used(self):
        """Test PhaseSummary with agents_used populated."""
        summary = PhaseSummary(
            phase_name="IMPLEMENTATION",
            model="opus",
            timeout=14400,
            started_at="2026-01-22T10:00:00+00:00",
            agents_used=["tdd-red-agent", "backend-agent"],
        )
        assert summary.agents_used == ["tdd-red-agent", "backend-agent"]

    def test_phase_summary_to_dict_includes_agents_used(self):
        """Test that to_dict includes agents_used."""
        summary = PhaseSummary(
            phase_name="IMPLEMENTATION",
            model="opus",
            timeout=14400,
            started_at="2026-01-22T10:00:00+00:00",
            agents_used=["backend-agent"],
        )
        d = summary.to_dict()
        assert "agents_used" in d
        assert d["agents_used"] == ["backend-agent"]


class TestWorkflowSummaryAllAgentsUsed:
    """Tests for all_agents_used field in WorkflowSummary dataclass."""

    def test_workflow_summary_default_all_agents_used(self):
        """Test that all_agents_used defaults to empty list."""
        summary = WorkflowSummary(
            feature_name="test-feature",
            started_at="2026-01-22T10:00:00+00:00",
        )
        assert summary.all_agents_used == []

    def test_workflow_summary_with_all_agents_used(self):
        """Test WorkflowSummary with all_agents_used populated."""
        summary = WorkflowSummary(
            feature_name="test-feature",
            started_at="2026-01-22T10:00:00+00:00",
            all_agents_used=["tdd-red-agent", "backend-agent"],
        )
        assert summary.all_agents_used == ["tdd-red-agent", "backend-agent"]

    def test_workflow_summary_to_dict_includes_all_agents_used(self):
        """Test that to_dict includes all_agents_used."""
        summary = WorkflowSummary(
            feature_name="test-feature",
            started_at="2026-01-22T10:00:00+00:00",
            all_agents_used=["backend-agent", "frontend-agent"],
        )
        d = summary.to_dict()
        assert "all_agents_used" in d
        assert d["all_agents_used"] == ["backend-agent", "frontend-agent"]
