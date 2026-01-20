"""Visualisation de progression temps réel pour Ralphy."""

import re
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn
from rich.text import Text


class ActivityType(Enum):
    """Types d'activité détectés dans l'output."""

    IDLE = "idle"
    WRITING_FILE = "writing_file"
    RUNNING_TEST = "running_test"
    RUNNING_COMMAND = "running_command"
    TASK_COMPLETE = "task_complete"
    READING_FILE = "reading_file"
    THINKING = "thinking"


@dataclass
class Activity:
    """Activité courante détectée."""

    type: ActivityType
    description: str
    detail: Optional[str] = None


# Patterns de détection d'activité
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
    ActivityType.TASK_COMPLETE: [
        r"\*\*Statut\*\*:\s*completed",
        r"[✓✔]\s*T(?:ask|âche)",
        r"Task.*completed",
        r"Tâche.*complétée",
        r"status.*completed",
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
}


class OutputParser:
    """Parse l'output Claude pour détecter les activités."""

    def __init__(self):
        self._compiled_patterns: dict[ActivityType, list[re.Pattern]] = {}
        self._compile_patterns()

    def _compile_patterns(self) -> None:
        """Compile les regex patterns."""
        for activity_type, patterns in ACTIVITY_PATTERNS.items():
            self._compiled_patterns[activity_type] = [
                re.compile(p, re.IGNORECASE | re.MULTILINE) for p in patterns
            ]

    def parse(self, text: str) -> Optional[Activity]:
        """Parse le texte et retourne l'activité détectée."""
        # Priorité: WRITING_FILE > RUNNING_TEST > RUNNING_COMMAND > TASK_COMPLETE > READING_FILE > THINKING
        priority_order = [
            ActivityType.WRITING_FILE,
            ActivityType.RUNNING_TEST,
            ActivityType.RUNNING_COMMAND,
            ActivityType.TASK_COMPLETE,
            ActivityType.READING_FILE,
            ActivityType.THINKING,
        ]

        for activity_type in priority_order:
            patterns = self._compiled_patterns.get(activity_type, [])
            for pattern in patterns:
                match = pattern.search(text)
                if match:
                    detail = match.group(1) if match.lastindex and match.lastindex >= 1 else None
                    return Activity(
                        type=activity_type,
                        description=self._get_description(activity_type, detail),
                        detail=detail,
                    )

        return None

    def _get_description(self, activity_type: ActivityType, detail: Optional[str]) -> str:
        """Génère une description lisible de l'activité."""
        descriptions = {
            ActivityType.WRITING_FILE: f"Writing {detail}" if detail else "Writing file",
            ActivityType.RUNNING_TEST: "Running tests",
            ActivityType.RUNNING_COMMAND: f"Running: {detail}" if detail else "Running command",
            ActivityType.TASK_COMPLETE: "Task completed",
            ActivityType.READING_FILE: f"Reading {detail}" if detail else "Reading file",
            ActivityType.THINKING: "Analyzing...",
        }
        return descriptions.get(activity_type, "Working...")


@dataclass
class ProgressState:
    """État de la progression."""

    phase_name: str = ""
    phase_progress: float = 0.0
    tasks_completed: int = 0
    tasks_total: int = 0
    current_activity: Optional[Activity] = None
    last_output_lines: list[str] = field(default_factory=list)


class ProgressDisplay:
    """Affichage de progression avec Rich Live."""

    MAX_OUTPUT_LINES = 3

    def __init__(self, console: Optional[Console] = None):
        self.console = console or Console()
        self._lock = threading.Lock()
        self._state = ProgressState()
        self._live: Optional[Live] = None
        self._parser = OutputParser()
        self._active = False

        # Progress bars
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

        # Task IDs
        self._phase_task_id: Optional[int] = None
        self._tasks_task_id: Optional[int] = None

    def start(self, phase_name: str, total_tasks: int = 0) -> None:
        """Démarre l'affichage de progression."""
        with self._lock:
            self._state = ProgressState(
                phase_name=phase_name.upper(),
                tasks_total=total_tasks,
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
            self._live = Live(
                self._render(),
                console=self.console,
                refresh_per_second=4,
                transient=True,
            )
            self._live.start()

    def stop(self) -> None:
        """Arrête l'affichage de progression."""
        with self._lock:
            self._active = False
            if self._live:
                self._live.stop()
                self._live = None

    def update_phase_progress(self, progress: float) -> None:
        """Met à jour la progression de la phase (0-100)."""
        with self._lock:
            self._state.phase_progress = min(100, max(0, progress))
            if self._phase_task_id is not None:
                self._phase_progress.update(
                    self._phase_task_id, completed=self._state.phase_progress
                )
            self._refresh()

    def update_tasks(self, completed: int, total: int) -> None:
        """Met à jour le compteur de tâches."""
        with self._lock:
            self._state.tasks_completed = completed
            self._state.tasks_total = total

            if self._tasks_task_id is None and total > 0:
                self._tasks_task_id = self._tasks_progress.add_task(
                    "Tasks", total=total, completed=completed
                )
            elif self._tasks_task_id is not None:
                self._tasks_progress.update(
                    self._tasks_task_id, completed=completed, total=total
                )

            # Calcul progression phase basée sur les tâches
            if total > 0:
                self._state.phase_progress = (completed / total) * 100
                if self._phase_task_id is not None:
                    self._phase_progress.update(
                        self._phase_task_id, completed=self._state.phase_progress
                    )

            self._refresh()

    def process_output(self, text: str) -> None:
        """Traite l'output et met à jour l'affichage."""
        with self._lock:
            # Détecte l'activité
            activity = self._parser.parse(text)
            if activity:
                self._state.current_activity = activity

                # Compte les tâches complétées
                if activity.type == ActivityType.TASK_COMPLETE:
                    self._state.tasks_completed += 1
                    if self._tasks_task_id is not None:
                        self._tasks_progress.update(
                            self._tasks_task_id,
                            completed=self._state.tasks_completed,
                        )
                    # Update phase progress
                    if self._state.tasks_total > 0:
                        self._state.phase_progress = (
                            self._state.tasks_completed / self._state.tasks_total
                        ) * 100
                        if self._phase_task_id is not None:
                            self._phase_progress.update(
                                self._phase_task_id,
                                completed=self._state.phase_progress,
                            )

            # Garde les dernières lignes d'output
            lines = text.strip().split("\n")
            for line in lines:
                line = line.strip()
                if line and len(line) > 2:
                    self._state.last_output_lines.append(line)
                    if len(self._state.last_output_lines) > self.MAX_OUTPUT_LINES:
                        self._state.last_output_lines.pop(0)

            self._refresh()

    def _refresh(self) -> None:
        """Rafraîchit l'affichage."""
        if self._live and self._active:
            self._live.update(self._render())

    def _render(self) -> Panel:
        """Génère le rendu du panel de progression."""
        elements = []

        # Progress bars
        elements.append(self._phase_progress)
        if self._tasks_task_id is not None:
            elements.append(self._tasks_progress)

        # Activité courante
        if self._state.current_activity:
            activity_text = Text()
            activity_text.append("\n● ", style="green bold")
            activity_text.append(self._state.current_activity.description)
            elements.append(activity_text)

        # Dernières lignes d'output
        if self._state.last_output_lines:
            output_text = Text("\n")
            for line in self._state.last_output_lines[-self.MAX_OUTPUT_LINES :]:
                # Tronque les lignes trop longues
                display_line = line[:80] + "..." if len(line) > 80 else line
                output_text.append("  > ", style="dim")
                output_text.append(display_line + "\n", style="dim")
            elements.append(output_text)

        return Panel(
            Group(*elements),
            title="[bold]Ralphy Progress[/bold]",
            border_style="blue",
        )

    @property
    def is_active(self) -> bool:
        """Retourne True si l'affichage est actif."""
        return self._active
