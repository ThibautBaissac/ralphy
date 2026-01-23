"""Workflow journal for persisting progress information to disk.

This module provides the WorkflowJournal class that captures all progress
events during Ralphy workflows and persists them for later analysis.
"""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from ralphy.claude import TokenUsage
    from ralphy.progress import Activity


class EventType(str, Enum):
    """Types of events that can be recorded in the journal."""

    WORKFLOW_START = "workflow_start"
    WORKFLOW_END = "workflow_end"
    PHASE_START = "phase_start"
    PHASE_END = "phase_end"
    TASK_START = "task_start"
    TASK_COMPLETE = "task_complete"
    ACTIVITY = "activity"
    TOKEN_UPDATE = "token_update"
    CIRCUIT_BREAKER = "circuit_breaker"
    VALIDATION = "validation"
    ERROR = "error"


@dataclass
class JournalEvent:
    """A single event in the workflow journal."""

    timestamp: str  # ISO 8601 format
    event_type: EventType
    phase: Optional[str]
    data: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert event to dictionary for JSON serialization."""
        return {
            "timestamp": self.timestamp,
            "event_type": self.event_type.value,
            "phase": self.phase,
            "data": self.data,
        }

    @classmethod
    def from_dict(cls, data: dict) -> JournalEvent:
        """Create JournalEvent from dictionary."""
        return cls(
            timestamp=data["timestamp"],
            event_type=EventType(data["event_type"]),
            phase=data.get("phase"),
            data=data.get("data", {}),
        )


@dataclass
class PhaseSummary:
    """Summary of a single phase execution."""

    phase_name: str
    model: str
    timeout: int
    started_at: str
    ended_at: Optional[str] = None
    duration_seconds: float = 0.0
    outcome: str = "unknown"
    tasks_total: int = 0
    tasks_completed: int = 0
    token_usage: Optional[dict] = None
    cost_usd: float = 0.0

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "phase_name": self.phase_name,
            "model": self.model,
            "timeout": self.timeout,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_seconds": self.duration_seconds,
            "outcome": self.outcome,
            "tasks_total": self.tasks_total,
            "tasks_completed": self.tasks_completed,
            "token_usage": self.token_usage,
            "cost_usd": self.cost_usd,
        }


@dataclass
class WorkflowSummary:
    """Summary of the entire workflow execution."""

    feature_name: str
    started_at: str
    ended_at: Optional[str] = None
    total_duration_seconds: float = 0.0
    outcome: str = "unknown"
    phases: list[PhaseSummary] = field(default_factory=list)
    total_cost_usd: float = 0.0
    total_tasks_completed: int = 0
    total_tasks_total: int = 0
    fresh_start: bool = False

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "feature_name": self.feature_name,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "total_duration_seconds": self.total_duration_seconds,
            "outcome": self.outcome,
            "phases": [p.to_dict() for p in self.phases],
            "total_cost_usd": self.total_cost_usd,
            "total_tasks_completed": self.total_tasks_completed,
            "total_tasks_total": self.total_tasks_total,
            "fresh_start": self.fresh_start,
        }


def _now_iso() -> str:
    """Get current timestamp in ISO 8601 format with UTC timezone."""
    return datetime.now(timezone.utc).isoformat()


class JournalWriter:
    """Handles file I/O operations for the workflow journal.

    Encapsulates all file operations (JSONL append, JSON write) to follow
    the Single Responsibility Principle. Thread-safe file operations.
    """

    def __init__(self, journal_path: Path, summary_path: Path):
        """Initialize the journal writer.

        Args:
            journal_path: Path to the JSONL event log file
            summary_path: Path to the JSON summary file
        """
        self._journal_path = journal_path
        self._summary_path = summary_path

    def _ensure_dir(self) -> None:
        """Ensure the parent directory exists."""
        self._journal_path.parent.mkdir(parents=True, exist_ok=True)

    def clear_journal(self) -> None:
        """Clear the journal file (for fresh starts)."""
        if self._journal_path.exists():
            self._journal_path.unlink()

    def append_event(self, event: JournalEvent) -> None:
        """Append a single event to the JSONL file.

        Args:
            event: The event to append
        """
        self._ensure_dir()
        with open(self._journal_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event.to_dict()) + "\n")

    def write_summary(self, summary: WorkflowSummary) -> None:
        """Write the workflow summary to JSON file.

        Args:
            summary: The workflow summary to write
        """
        self._ensure_dir()
        with open(self._summary_path, "w", encoding="utf-8") as f:
            json.dump(summary.to_dict(), f, indent=2)


class WorkflowJournal:
    """Thread-safe journal for workflow progress events.

    Writes events to a JSONL file in real-time and generates a summary
    JSON file at workflow end. Delegates file I/O to JournalWriter.

    Files are written to .ralphy/ directory within the feature directory:
    - progress.jsonl: Real-time event log (append-only)
    - progress_summary.json: Aggregate summary at workflow end
    """

    def __init__(self, feature_dir: Path, feature_name: str):
        """Initialize the workflow journal.

        Args:
            feature_dir: Path to the feature directory
            feature_name: Name of the feature being processed
        """
        self.feature_dir = feature_dir
        self.feature_name = feature_name
        self._lock = threading.Lock()
        self._summary: Optional[WorkflowSummary] = None
        self._current_phase: Optional[PhaseSummary] = None
        self._current_phase_name: Optional[str] = None
        self._started = False

        # Import constants here to avoid circular import
        from ralphy.constants import JOURNAL_FILE, JOURNAL_SUMMARY_FILE

        journal_path = feature_dir / ".ralphy" / JOURNAL_FILE
        summary_path = feature_dir / ".ralphy" / JOURNAL_SUMMARY_FILE
        self._writer = JournalWriter(journal_path, summary_path)

    def _create_event(
        self,
        event_type: EventType,
        phase: Optional[str] = None,
        **data: Any,
    ) -> JournalEvent:
        """Create a JournalEvent with current timestamp.

        Helper method to reduce duplication in record_* methods.

        Args:
            event_type: Type of the event
            phase: Phase name (uses current phase if None)
            **data: Additional data fields for the event

        Returns:
            JournalEvent with timestamp and provided data
        """
        return JournalEvent(
            timestamp=_now_iso(),
            event_type=event_type,
            phase=phase if phase is not None else self._current_phase_name,
            data=data,
        )

    def start_workflow(self, fresh: bool = False) -> None:
        """Record workflow start event.

        Args:
            fresh: Whether this is a fresh start (ignoring previous state)
        """
        with self._lock:
            if self._started:
                return

            self._started = True
            now = _now_iso()

            # Clear previous journal if fresh start
            if fresh:
                self._writer.clear_journal()

            self._summary = WorkflowSummary(
                feature_name=self.feature_name,
                started_at=now,
                fresh_start=fresh,
            )

            # Use captured `now` timestamp for consistency with _summary.started_at
            event = JournalEvent(
                timestamp=now,
                event_type=EventType.WORKFLOW_START,
                phase=None,
                data={"feature": self.feature_name, "fresh": fresh},
            )
            self._writer.append_event(event)

    def end_workflow(self, outcome: str) -> None:
        """Record workflow end event and write summary.

        Args:
            outcome: Final outcome (e.g., "completed", "failed", "aborted")
        """
        with self._lock:
            if not self._started or not self._summary:
                return

            now = _now_iso()
            self._summary.ended_at = now
            self._summary.outcome = outcome

            # Calculate total duration
            start_dt = datetime.fromisoformat(self._summary.started_at)
            end_dt = datetime.fromisoformat(now)
            self._summary.total_duration_seconds = (end_dt - start_dt).total_seconds()

            # Aggregate totals from phases
            self._summary.total_cost_usd = sum(p.cost_usd for p in self._summary.phases)
            self._summary.total_tasks_completed = sum(
                p.tasks_completed for p in self._summary.phases
            )
            self._summary.total_tasks_total = max(
                (p.tasks_total for p in self._summary.phases), default=0
            )

            event = JournalEvent(
                timestamp=now,
                event_type=EventType.WORKFLOW_END,
                phase=None,
                data={
                    "outcome": outcome,
                    "duration_seconds": self._summary.total_duration_seconds,
                    "total_cost_usd": self._summary.total_cost_usd,
                },
            )
            self._writer.append_event(event)
            self._writer.write_summary(self._summary)

    def start_phase(
        self,
        phase: str,
        model: str = "",
        timeout: int = 0,
        tasks_total: int = 0,
    ) -> None:
        """Record phase start event.

        Args:
            phase: Name of the phase (e.g., "SPECIFICATION", "IMPLEMENTATION")
            model: Model being used for this phase
            timeout: Timeout in seconds for this phase
            tasks_total: Total number of tasks in this phase
        """
        with self._lock:
            if not self._started:
                return

            now = _now_iso()
            self._current_phase_name = phase
            self._current_phase = PhaseSummary(
                phase_name=phase,
                model=model,
                timeout=timeout,
                started_at=now,
                tasks_total=tasks_total,
            )

            event = JournalEvent(
                timestamp=now,
                event_type=EventType.PHASE_START,
                phase=phase,
                data={
                    "model": model,
                    "timeout": timeout,
                    "tasks_total": tasks_total,
                },
            )
            self._writer.append_event(event)

    def end_phase(
        self,
        outcome: str,
        token_usage: Optional[dict] = None,
        cost: float = 0.0,
        tasks_completed: int = 0,
    ) -> None:
        """Record phase end event.

        Args:
            outcome: Phase outcome (e.g., "success", "failed", "timeout")
            token_usage: Dictionary of token usage statistics
            cost: Cost in USD for this phase
            tasks_completed: Number of tasks completed in this phase
        """
        with self._lock:
            if not self._started or not self._current_phase:
                return

            now = _now_iso()
            phase = self._current_phase

            phase.ended_at = now
            phase.outcome = outcome
            phase.token_usage = token_usage
            phase.cost_usd = cost
            phase.tasks_completed = tasks_completed

            # Calculate duration
            start_dt = datetime.fromisoformat(phase.started_at)
            end_dt = datetime.fromisoformat(now)
            phase.duration_seconds = (end_dt - start_dt).total_seconds()

            if self._summary:
                self._summary.phases.append(phase)

            event = JournalEvent(
                timestamp=now,
                event_type=EventType.PHASE_END,
                phase=phase.phase_name,
                data={
                    "outcome": outcome,
                    "duration_seconds": phase.duration_seconds,
                    "cost_usd": cost,
                    "tasks_completed": tasks_completed,
                    "token_usage": token_usage,
                },
            )
            self._writer.append_event(event)

            self._current_phase = None
            self._current_phase_name = None

    def record_task_event(
        self,
        event_type: str,
        task_id: Optional[str],
        task_name: Optional[str] = None,
    ) -> None:
        """Record a task start or completion event.

        Args:
            event_type: Either "start" or "complete"
            task_id: ID of the task (e.g., "1.2", "2.3")
            task_name: Optional human-readable name of the task
        """
        with self._lock:
            if not self._started:
                return

            journal_event_type = (
                EventType.TASK_START if event_type == "start" else EventType.TASK_COMPLETE
            )

            event = self._create_event(
                journal_event_type,
                task_id=task_id,
                task_name=task_name,
            )
            self._writer.append_event(event)

    def record_activity(self, activity: Activity) -> None:
        """Record a detected activity event.

        Args:
            activity: The Activity object from progress parsing
        """
        with self._lock:
            if not self._started:
                return

            event = self._create_event(
                EventType.ACTIVITY,
                type=activity.type.value,
                description=activity.description,
                detail=activity.detail,
            )
            self._writer.append_event(event)

    def record_token_update(self, usage: TokenUsage, cost: float) -> None:
        """Record a token usage update.

        Args:
            usage: TokenUsage instance with current counts
            cost: Total cost in USD
        """
        with self._lock:
            if not self._started:
                return

            event = self._create_event(
                EventType.TOKEN_UPDATE,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cache_read_tokens=usage.cache_read_tokens,
                cache_creation_tokens=usage.cache_creation_tokens,
                total_tokens=usage.total_tokens,
                context_utilization=usage.context_utilization,
                cost_usd=cost,
            )
            self._writer.append_event(event)

            # Update current phase cost tracking
            if self._current_phase:
                self._current_phase.cost_usd = cost
                self._current_phase.token_usage = {
                    "input_tokens": usage.input_tokens,
                    "output_tokens": usage.output_tokens,
                    "cache_read_tokens": usage.cache_read_tokens,
                    "cache_creation_tokens": usage.cache_creation_tokens,
                }

    def record_circuit_breaker(
        self,
        trigger_type: str,
        attempts: int,
        is_open: bool,
    ) -> None:
        """Record a circuit breaker event.

        Args:
            trigger_type: Type of trigger (e.g., "INACTIVITY", "REPEATED_ERROR")
            attempts: Number of attempts/warnings before this event
            is_open: Whether the circuit breaker is now open (tripped)
        """
        with self._lock:
            if not self._started:
                return

            event = self._create_event(
                EventType.CIRCUIT_BREAKER,
                trigger_type=trigger_type,
                attempts=attempts,
                is_open=is_open,
            )
            self._writer.append_event(event)

    def record_validation(
        self,
        phase: str,
        approved: bool,
        feedback: Optional[str] = None,
    ) -> None:
        """Record a human validation event.

        Args:
            phase: Phase being validated (e.g., "SPECIFICATION", "QA")
            approved: Whether the validation was approved
            feedback: Optional feedback from the user
        """
        with self._lock:
            if not self._started:
                return

            event = self._create_event(
                EventType.VALIDATION,
                phase=phase,
                approved=approved,
                feedback=feedback,
            )
            self._writer.append_event(event)

    def record_error(self, error_message: str, error_type: str = "unknown") -> None:
        """Record an error event.

        Args:
            error_message: Description of the error
            error_type: Type of error (e.g., "timeout", "circuit_breaker", "validation")
        """
        with self._lock:
            if not self._started:
                return

            event = self._create_event(
                EventType.ERROR,
                error_type=error_type,
                message=error_message,
            )
            self._writer.append_event(event)

    @property
    def is_started(self) -> bool:
        """Check if the journal has been started."""
        with self._lock:
            return self._started
