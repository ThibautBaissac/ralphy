"""Real-time progress visualization for Ralphy."""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Callable, Optional

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn
from rich.rule import Rule
from rich.text import Text

if TYPE_CHECKING:
    from ralphy.claude import TokenUsage


class ActivityType(Enum):
    """Types of activity detected in output."""

    IDLE = "idle"
    WRITING_FILE = "writing_file"
    RUNNING_TEST = "running_test"
    RUNNING_COMMAND = "running_command"
    TASK_START = "task_start"
    TASK_COMPLETE = "task_complete"
    READING_FILE = "reading_file"
    THINKING = "thinking"
    AGENT_DELEGATION = "agent_delegation"


@dataclass
class Activity:
    """Current detected activity."""

    type: ActivityType
    description: str
    detail: Optional[str] = None


# Activity detection patterns
ACTIVITY_PATTERNS: dict[ActivityType, list[str]] = {
    ActivityType.WRITING_FILE: [
        r"(?:Writing|Creating|Wrote)\s+[`'\"]?([^\s`'\"]+\.[a-z]+)",
        r"Write\s+[`'\"]?([^\s`'\"]+\.[a-z]+)",
        r"Editing\s+[`'\"]?([^\s`'\"]+\.[a-z]+)",
    ],
    ActivityType.RUNNING_TEST: [
        r"(?:bundle exec )?rspec",
        r"Running tests",
        r"pytest",
        r"npm test",
        r"yarn test",
        r"\d+ examples?,\s*\d+ failures?",
    ],
    ActivityType.RUNNING_COMMAND: [
        r"Running:\s*(.+)$",
        r"Executing:\s*(.+)$",
        r"\$\s+(.+)$",
        r"bundle exec",
        r"rails \w+",
    ],
    ActivityType.TASK_START: [
        r"\*\*Status\*\*:\s*in_progress",  # Detects when a task transitions to in_progress
        r"###\s*Task\s*([\d.]+).*\[([^\]]+)\]",
        r"Working on Task\s*([\d.]+)",
        r"Starting Task\s*([\d.]+)",
        r"Implementing Task\s*([\d.]+)",
        r"Now (?:implementing|working on)\s*Task\s*([\d.]+)",
        r"pending.*→.*in_progress",  # Edit tool changing status
    ],
    ActivityType.TASK_COMPLETE: [
        r"\*\*Status\*\*:\s*completed",
        r"[✓✔]\s*Task",
        r"Task\s*([\d.]+).*completed",
        r"Completed\s*Task\s*([\d.]+)",
        r"status.*completed",
        r"in_progress.*→.*completed",  # Edit tool changing status
    ],
    ActivityType.READING_FILE: [
        r"Reading\s+[`'\"]?([^\s`'\"]+)",
        r"Read\s+[`'\"]?([^\s`'\"]+\.[a-z]+)",
    ],
    ActivityType.THINKING: [
        r"Let me",
        r"I'll",
        r"I will",
        r"Analyzing",
        r"Checking",
    ],
    ActivityType.AGENT_DELEGATION: [
        # Matches: "delegate to model-agent", "delegating this to the tdd-orchestrator-agent"
        # MUST have "to" before agent name - captures agent name with -agent suffix required
        r"(?:delegate|delegating)\s+(?:\w+\s+)*?to\s+(?:the\s+)?([a-z0-9_-]+-agent)",
        # Matches: "I'll use the model-agent", "using tdd-orchestrator-agent"
        r"(?:use|using|invoke|invoking)\s+(?:the\s+)?([a-z0-9_-]+-agent)",
        # Matches Task tool subagent_type in JSON stream output
        r'"subagent_type":\s*"([a-z0-9_-]+)"',
    ],
}


class OutputParser:
    """Parses Claude output to detect activities."""

    def __init__(self):
        self._compiled_patterns: dict[ActivityType, list[re.Pattern]] = {}
        self._compile_patterns()

    def _compile_patterns(self) -> None:
        """Compiles regex patterns."""
        for activity_type, patterns in ACTIVITY_PATTERNS.items():
            self._compiled_patterns[activity_type] = [
                re.compile(p, re.IGNORECASE | re.MULTILINE) for p in patterns
            ]

    def parse(self, text: str) -> Optional[Activity]:
        """Parses text and returns detected activity."""
        # Priority: TASK_START/COMPLETE detected first for logging,
        # AGENT_DELEGATION high priority to detect agent handoffs
        priority_order = [
            ActivityType.TASK_START,
            ActivityType.TASK_COMPLETE,
            ActivityType.AGENT_DELEGATION,
            ActivityType.WRITING_FILE,
            ActivityType.RUNNING_TEST,
            ActivityType.RUNNING_COMMAND,
            ActivityType.READING_FILE,
            ActivityType.THINKING,
        ]

        for activity_type in priority_order:
            patterns = self._compiled_patterns.get(activity_type, [])
            for pattern in patterns:
                match = pattern.search(text)
                if match:
                    # Extract captured groups
                    detail = match.group(1) if match.lastindex and match.lastindex >= 1 else None
                    # For TASK_START, group 2 contains the task name
                    detail2 = match.group(2) if match.lastindex and match.lastindex >= 2 else None
                    return Activity(
                        type=activity_type,
                        description=self._get_description(activity_type, detail, detail2),
                        detail=f"{detail}:{detail2}" if detail2 else detail,
                    )

        return None

    def _get_description(
        self, activity_type: ActivityType, detail: Optional[str], detail2: Optional[str] = None
    ) -> str:
        """Generates a readable activity description."""
        descriptions = {
            ActivityType.TASK_START: f"Task {detail}: {detail2}" if detail2 else f"Starting task {detail}" if detail else "Starting task",
            ActivityType.TASK_COMPLETE: f"Completed task {detail}" if detail else "Task completed",
            ActivityType.AGENT_DELEGATION: f"Delegating to {detail}" if detail else "Delegating to agent",
            ActivityType.WRITING_FILE: f"Writing {detail}" if detail else "Writing file",
            ActivityType.RUNNING_TEST: "Running tests",
            ActivityType.RUNNING_COMMAND: f"Running: {detail}" if detail else "Running command",
            ActivityType.READING_FILE: f"Reading {detail}" if detail else "Reading file",
            ActivityType.THINKING: "Analyzing...",
        }
        return descriptions.get(activity_type, "Working...")

    def parse_all_completions(self, text: str) -> list[str]:
        """Extract all completed task IDs from text.

        Matches patterns like:
        - ### Task 1.2 ... **Status**: completed
        - ## Task 2 ... **Status**: completed
        - Task 1.2 completed
        - in_progress → completed (for task ID in context)

        This method scans the entire text for ALL completion markers,
        unlike parse() which returns on the first match.

        Returns:
            List of task IDs (e.g., ["1", "1.2", "2.3"]) that are marked completed.
        """
        completed_ids: list[str] = []

        # Pattern 1: Task header with status on same logical block
        # Matches: ### Task 1.2 - Name\n**Status**: completed
        task_block_pattern = re.compile(
            r"#{2,3}\s*Task\s*([\d.]+).*?(?:\*\*Status\*\*:\s*completed)",
            re.IGNORECASE | re.DOTALL
        )
        for match in task_block_pattern.finditer(text):
            task_id = match.group(1)
            if task_id and task_id not in completed_ids:
                completed_ids.append(task_id)

        # Pattern 2: Explicit completion statements
        # Matches: "Task 1.2 completed", "Completed Task 1.2"
        explicit_pattern = re.compile(
            r"(?:Task\s*([\d.]+).*?completed|Completed\s*Task\s*([\d.]+))",
            re.IGNORECASE
        )
        for match in explicit_pattern.finditer(text):
            task_id = match.group(1) or match.group(2)
            if task_id and task_id not in completed_ids:
                completed_ids.append(task_id)

        return completed_ids


@dataclass
class ProgressState:
    """Progress state."""

    phase_name: str = ""
    phase_progress: float = 0.0
    tasks_completed: int = 0
    tasks_total: int = 0
    current_activity: Optional[Activity] = None
    current_task_id: Optional[str] = None  # E.g., "1.9"
    current_task_name: Optional[str] = None  # E.g., "Model - Create Team model"
    last_output_lines: list[str] = field(default_factory=list)
    # New fields for enriched display
    model_name: str = ""
    phase_started_at: Optional[datetime] = None
    phase_timeout: int = 0  # seconds
    feature_name: str = ""
    # Token usage tracking
    token_usage: Optional[TokenUsage] = None
    total_cost_usd: float = 0.0
    # TDD and agent info
    tdd_enabled: bool = False
    agent_name: str = ""
    available_agents: list[str] = field(default_factory=list)
    delegated_from: Optional[str] = None  # Original agent if delegation occurred
    # In-memory task completion counter (incremented on TASK_COMPLETE detection)
    # This avoids race condition where file isn't written yet when callback fires
    detected_completed: int = 0
    detected_task_ids: set[str] = field(default_factory=set)  # Track detected task IDs to avoid double counting


@dataclass
class RenderContext:
    """Context for rendering the progress panel.

    Groups together all the data needed by ProgressRenderer to generate
    a Rich Panel. This separates rendering concerns from state management.
    """

    state: ProgressState
    phase_progress: Progress
    tasks_progress: Progress
    phase_task_id: Optional[int]
    tasks_task_id: Optional[int]


class ProgressRenderer:
    """Stateless renderer for progress panels.

    Generates Rich Panel elements from RenderContext. Separated from
    ProgressDisplay to follow Single Responsibility Principle.
    """

    MAX_OUTPUT_LINES = 3

    @staticmethod
    def format_elapsed(elapsed_seconds: float) -> str:
        """Format elapsed time as HH:MM:SS or MM:SS."""
        minutes, seconds = divmod(int(elapsed_seconds), 60)
        hours, minutes = divmod(minutes, 60)
        if hours > 0:
            return f"{hours:d}h{minutes:02d}m{seconds:02d}s"
        return f"{minutes:02d}:{seconds:02d}"

    @staticmethod
    def format_timeout(timeout_seconds: int) -> str:
        """Format timeout for display (e.g., '4h00m', '30m')."""
        hours, remainder = divmod(timeout_seconds, 3600)
        minutes = remainder // 60
        if hours > 0:
            return f"{hours}h{minutes:02d}m"
        return f"{minutes}m"

    def render(self, context: RenderContext) -> Panel:
        """Generate the progress panel from render context.

        Args:
            context: RenderContext containing state and progress bars

        Returns:
            Rich Panel with formatted progress display
        """
        elements = []
        state = context.state

        # Header section: Feature name
        if state.feature_name:
            feature_text = Text()
            feature_text.append("Feature: ", style="dim")
            feature_text.append(state.feature_name, style="bold cyan")
            elements.append(feature_text)

        # Phase and model line
        info_line = Text()
        info_line.append("Phase: ", style="dim")
        info_line.append(state.phase_name, style="bold yellow")
        if state.model_name:
            info_line.append("  Model: ", style="dim")
            info_line.append(state.model_name, style="bold magenta")
        elements.append(info_line)

        # Agent and TDD status line
        if state.agent_name:
            agent_line = Text()
            agent_line.append("Agent: ", style="dim")
            agent_line.append(state.agent_name, style="cyan")
            # Show delegation context or available agents count
            if state.delegated_from and state.delegated_from != state.agent_name:
                agent_line.append(f" (via {state.delegated_from})", style="dim italic")
            elif state.available_agents:
                agent_line.append(f" (+{len(state.available_agents)} available)", style="dim")
            agent_line.append("  TDD: ", style="dim")
            if state.tdd_enabled:
                agent_line.append("enabled", style="green bold")
            else:
                agent_line.append("disabled", style="dim")
            elements.append(agent_line)

        # Elapsed time and timeout line
        if state.phase_started_at:
            elapsed = (datetime.now() - state.phase_started_at).total_seconds()
            time_line = Text()
            time_line.append("Elapsed: ", style="dim")
            time_line.append(self.format_elapsed(elapsed), style="bold green")
            if state.phase_timeout > 0:
                time_line.append("  Timeout: ", style="dim")
                time_line.append(self.format_timeout(state.phase_timeout), style="bold")
            elements.append(time_line)

        # Context window and cost line
        if state.token_usage:
            usage = state.token_usage
            utilization = usage.context_utilization
            context_line = Text()
            context_line.append("Context: ", style="dim")

            # Color code utilization: green < 60%, yellow 60-80%, red > 80%
            if utilization < 60:
                util_style = "bold green"
            elif utilization < 80:
                util_style = "bold yellow"
            else:
                util_style = "bold red"

            context_line.append(f"{utilization:.1f}%", style=util_style)
            context_line.append(
                f" ({usage.total_tokens:,}/{usage.context_window:,} tokens)", style="dim"
            )

            # Add cost if available
            if state.total_cost_usd > 0:
                context_line.append("  Cost: ", style="dim")
                context_line.append(f"${state.total_cost_usd:.4f}", style="bold")

            elements.append(context_line)

        # Separator before progress bars
        elements.append(Rule(style="dim"))

        # Progress bars
        elements.append(context.phase_progress)
        if context.tasks_task_id is not None:
            elements.append(context.tasks_progress)

        # Separator before activity
        elements.append(Rule(style="dim"))

        # Current task (more prominent)
        if state.current_task_id:
            task_text = Text()
            task_text.append("● ", style="green bold")
            task_text.append(f"Task {state.current_task_id}", style="bold")
            if state.current_task_name:
                task_text.append(f": {state.current_task_name}", style="")
            elements.append(task_text)

        # Current activity (sub-detail)
        if state.current_activity:
            activity_text = Text()
            activity_text.append("  > ", style="dim")
            activity_text.append(state.current_activity.description, style="dim italic")
            elements.append(activity_text)
        elif not state.current_task_id:
            # Show generic activity when no task is active
            activity_text = Text()
            activity_text.append("● ", style="green bold")
            activity_text.append("Working...", style="dim italic")
            elements.append(activity_text)

        # Last output lines (reduced prominence)
        if state.last_output_lines:
            output_text = Text()
            for line in state.last_output_lines[-self.MAX_OUTPUT_LINES:]:
                display_line = line
                output_text.append("  > ", style="dim")
                output_text.append(display_line + "\n", style="dim")
            elements.append(output_text)

        return Panel(
            Group(*elements),
            title="[bold]Ralphy Progress[/bold]",
            border_style="blue",
        )


class ProgressDisplay:
    """Progress display with Rich Live.

    Coordinates progress state management and rendering. Delegates
    panel rendering to ProgressRenderer for SRP compliance.
    """

    MAX_OUTPUT_LINES = 3

    def __init__(
        self,
        console: Optional[Console] = None,
        on_task_event: Optional[callable] = None,
        on_activity: Optional[Callable[[Activity], None]] = None,
    ):
        self.console = console or Console()
        self._lock = threading.Lock()
        self._state = ProgressState()
        self._live: Optional[Live] = None
        self._parser = OutputParser()
        self._active = False
        self._on_task_event = on_task_event  # Callback(event_type, task_id, task_name)
        self._on_activity = on_activity  # Callback(activity) for detected activities
        self._renderer = ProgressRenderer()

        # Progress bars (created in start())
        self._phase_progress: Optional[Progress] = None
        self._tasks_progress: Optional[Progress] = None

        # Task IDs
        self._phase_task_id: Optional[int] = None
        self._tasks_task_id: Optional[int] = None

    def start(
        self,
        phase_name: str,
        total_tasks: int = 0,
        model: str = "",
        timeout: int = 0,
        feature_name: str = "",
        tdd_enabled: bool = False,
        agent_name: str = "",
        available_agents: Optional[list[str]] = None,
    ) -> None:
        """Starts progress display."""
        with self._lock:
            self._state = ProgressState(
                phase_name=phase_name.upper(),
                tasks_total=total_tasks,
                model_name=model,
                phase_started_at=datetime.now(),
                phase_timeout=timeout,
                feature_name=feature_name,
                tdd_enabled=tdd_enabled,
                agent_name=agent_name,
                available_agents=available_agents or [],
                detected_completed=0,
                detected_task_ids=set(),
            )

            # Reset progress bars
            self._phase_progress = Progress(
                SpinnerColumn(),
                TextColumn("[bold cyan]{task.description}"),
                BarColumn(bar_width=30),
                TaskProgressColumn(),
                console=self.console,
            )
            self._tasks_progress = Progress(
                SpinnerColumn(),
                TextColumn("[bold blue]{task.description}"),
                BarColumn(bar_width=30),
                TextColumn("[progress.percentage]{task.completed}/{task.total} completed"),
                console=self.console,
            )

            self._phase_task_id = self._phase_progress.add_task(
                phase_name.upper(), total=100, completed=0
            )

            if total_tasks > 0:
                self._tasks_task_id = self._tasks_progress.add_task(
                    "Tasks", total=total_tasks, completed=0
                )
            else:
                self._tasks_task_id = None

            self._active = True
            # Pass self as renderable - Rich will call __rich__() on each refresh
            # This ensures the display always reflects current state
            self._live = Live(
                self,  # ProgressDisplay implements __rich__()
                console=self.console,
                refresh_per_second=4,
                transient=True,
            )
            self._live.start()

    def stop(self) -> None:
        """Stops progress display."""
        with self._lock:
            self._active = False
            if self._live:
                self._live.stop()
                self._live = None

    def update_phase_progress(self, progress: float) -> None:
        """Updates phase progress (0-100)."""
        with self._lock:
            self._state.phase_progress = min(100, max(0, progress))
            if self._phase_task_id is not None:
                self._phase_progress.update(
                    self._phase_task_id, completed=self._state.phase_progress
                )
            self._refresh()

    def update_tasks(self, completed: int, total: int, from_thread: bool = False) -> None:
        """Updates task counter.

        Args:
            completed: Number of completed tasks
            total: Total number of tasks
            from_thread: If True, skip _refresh() as Rich Live isn't thread-safe.
                        The auto-refresh (4/sec) will pick up state changes.
        """
        with self._lock:
            self._state.tasks_completed = completed
            self._state.tasks_total = total
            # Sync detected counter if file-based count is higher (authoritative source)
            # This ensures polling thread's file-based count can correct any detection misses
            self._state.detected_completed = max(self._state.detected_completed, completed)

            if self._tasks_task_id is None and total > 0:
                self._tasks_task_id = self._tasks_progress.add_task(
                    "Tasks", total=total, completed=completed
                )
            elif self._tasks_task_id is not None:
                # Use max of both counts to handle race conditions
                effective_completed = max(completed, self._state.detected_completed)
                self._tasks_progress.update(
                    self._tasks_task_id, completed=effective_completed, total=total
                )

            # Calculate phase progress based on best available count
            if total > 0:
                effective_completed = max(completed, self._state.detected_completed)
                self._state.phase_progress = (effective_completed / total) * 100
                if self._phase_task_id is not None:
                    self._phase_progress.update(
                        self._phase_task_id, completed=self._state.phase_progress
                    )

            # Skip refresh if called from background thread (Rich Live isn't thread-safe)
            if not from_thread:
                self._refresh()

    def process_output(self, text: str) -> None:
        """Processes output and updates display."""
        with self._lock:
            # Detects activity
            activity = self._parser.parse(text)
            if activity:
                self._state.current_activity = activity

                # Invoke activity callback for journal logging
                if self._on_activity:
                    self._on_activity(activity)

                # Handles task start
                if activity.type == ActivityType.TASK_START:
                    # Clear old output lines when starting a new task
                    # This prevents the display from appearing "frozen" on earlier messages
                    self._state.last_output_lines.clear()
                    # detail format: "task_id:task_name" or just "task_id"
                    if activity.detail and ":" in activity.detail:
                        parts = activity.detail.split(":", 1)
                        self._state.current_task_id = parts[0]
                        self._state.current_task_name = parts[1] if len(parts) > 1 else None
                    else:
                        self._state.current_task_id = activity.detail
                        self._state.current_task_name = None
                    # Callback for logging
                    if self._on_task_event:
                        self._on_task_event(
                            "start",
                            self._state.current_task_id,
                            self._state.current_task_name,
                        )

                # Task completion detected - extract ALL completed task IDs from text
                # This fixes the issue where parse() only returns the first match
                elif activity.type == ActivityType.TASK_COMPLETE:
                    # Extract all completed task IDs from the full text
                    completed_ids = self._parser.parse_all_completions(text)

                    # Fall back to single task ID detection if parse_all_completions finds nothing
                    if not completed_ids:
                        fallback_id = activity.detail or self._state.current_task_id
                        completed_ids = [fallback_id] if fallback_id else []

                    # Process each newly completed task
                    new_completions = False
                    for task_id in completed_ids:
                        if task_id not in self._state.detected_task_ids:
                            self._state.detected_task_ids.add(task_id)
                            self._state.detected_completed += 1
                            new_completions = True
                            # Fire callback for each completion
                            if self._on_task_event:
                                self._on_task_event("complete", task_id, None)

                    # If no task IDs were found at all, still fire callback once (for journal logging)
                    # This preserves backward compatibility where completion events are logged
                    if not completed_ids and self._on_task_event:
                        self._on_task_event("complete", None, self._state.current_task_name)

                    # Update progress bar with total detected completions
                    if new_completions and self._tasks_task_id is not None and self._state.tasks_total > 0:
                        self._tasks_progress.update(
                            self._tasks_task_id,
                            completed=self._state.detected_completed
                        )
                        # Update phase progress based on in-memory count
                        self._state.phase_progress = (self._state.detected_completed / self._state.tasks_total) * 100
                        if self._phase_task_id is not None:
                            self._phase_progress.update(
                                self._phase_task_id,
                                completed=self._state.phase_progress
                            )

                    # Reset current task
                    self._state.current_task_id = None
                    self._state.current_task_name = None

                    # Reset agent to original if we were in a delegated state
                    if self._state.delegated_from:
                        self._state.agent_name = self._state.delegated_from
                        self._state.delegated_from = None

                # Agent delegation detected - update current agent display
                elif activity.type == ActivityType.AGENT_DELEGATION:
                    if activity.detail:
                        # Normalize agent name (e.g., "model" -> "model-agent")
                        new_agent = activity.detail.lower().strip()
                        if not new_agent.endswith("-agent"):
                            new_agent = f"{new_agent}-agent"

                        # Only update if different from current and agent is available
                        if new_agent != self._state.agent_name:
                            # Check if new agent matches one in available_agents list
                            is_known_agent = new_agent in self._state.available_agents or any(
                                a.lower() == new_agent or a.lower().startswith(new_agent.replace("-agent", ""))
                                for a in self._state.available_agents
                            )
                            if is_known_agent:
                                # Store original agent for later reset
                                if not self._state.delegated_from:
                                    self._state.delegated_from = self._state.agent_name
                                self._state.agent_name = new_agent

            # Keeps last output lines
            lines = text.strip().split("\n")
            for line in lines:
                line = line.strip()
                if line and len(line) > 2:
                    self._state.last_output_lines.append(line)
                    if len(self._state.last_output_lines) > self.MAX_OUTPUT_LINES:
                        self._state.last_output_lines.pop(0)

            self._refresh()

    def update_token_usage(self, usage: TokenUsage, cost: float = 0.0) -> None:
        """Update token usage and cost display.

        Args:
            usage: TokenUsage instance with current token counts
            cost: Total cost in USD
        """
        with self._lock:
            self._state.token_usage = usage
            self._state.total_cost_usd = cost
            self._refresh()

    def update_available_agents(self, available_agents: list[str]) -> None:
        """Update the list of available agents for orchestration display.

        Args:
            available_agents: List of agent names discovered in .claude/agents/
        """
        with self._lock:
            self._state.available_agents = available_agents
            self._refresh()

    def _build_render_context(self) -> RenderContext:
        """Build render context from current state.

        Returns:
            RenderContext with current state and progress bars
        """
        return RenderContext(
            state=self._state,
            phase_progress=self._phase_progress,
            tasks_progress=self._tasks_progress,
            phase_task_id=self._phase_task_id,
            tasks_task_id=self._tasks_task_id,
        )

    def _refresh(self) -> None:
        """Request display refresh (handled by Rich Live auto-refresh).

        This is a no-op. Rich Live automatically refreshes at 4/sec by
        calling __rich__(). State changes will be picked up on the next
        refresh cycle (max 250ms latency).

        Method retained for API compatibility with existing callers.

        Note: This method expects the caller to hold self._lock.
        """
        pass

    def __rich__(self) -> Panel:
        """Make ProgressDisplay a Rich renderable.

        This method is called by Rich Live on each refresh, ensuring
        the display always reflects the current state.

        Important: We force-update the Progress objects here because they
        hold their own internal state that may not reflect our ProgressState.
        This ensures the progress bars always show the correct values.
        """
        with self._lock:
            # Force progress bar values to reflect current state
            # This fixes the issue where Progress objects don't auto-update
            if self._phase_task_id is not None:
                self._phase_progress.update(
                    self._phase_task_id,
                    completed=self._state.phase_progress
                )
            if self._tasks_task_id is not None:
                # Use max of file-based count and detected count to handle race conditions
                completed = max(self._state.tasks_completed, self._state.detected_completed)
                self._tasks_progress.update(
                    self._tasks_task_id,
                    completed=completed,
                    total=self._state.tasks_total
                )
            context = self._build_render_context()
            return self._renderer.render(context)

    @property
    def is_active(self) -> bool:
        """Returns True if display is active."""
        return self._active
