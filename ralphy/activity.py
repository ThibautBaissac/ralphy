"""Activity detection for Ralphy output parsing."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional


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
        # Matches: "delegate to model-agent", "delegating this to the TDD red agent"
        # MUST have "to" before agent name - captures agent name (case-insensitive, allows spaces)
        r"(?:delegate|delegating)\s+(?:\w+\s+)*?to\s+(?:the\s+)?([a-zA-Z0-9][a-zA-Z0-9_ -]*(?:agent)?)",
        # Matches: "I'll use the model-agent", "using TDD red agent", "let me use the backend-agent"
        r"(?:let\s+me\s+)?(?:use|using|invoke|invoking)\s+(?:the\s+)?([a-zA-Z0-9][a-zA-Z0-9_ -]*(?:agent)?)",
        # Matches Task tool subagent_type in JSON stream output
        r'"subagent_type":\s*"([a-zA-Z0-9_-]+)"',
    ],
}


def normalize_agent_name(raw_name: str) -> str:
    """Normalize agent name to canonical hyphenated lowercase form.

    Converts various formats to a consistent agent name:
    - "TDD red agent" -> "tdd-red-agent"
    - "backend_agent" -> "backend-agent"
    - "model" -> "model-agent"
    - "TDD-red" -> "tdd-red-agent"

    Args:
        raw_name: Raw agent name captured from output

    Returns:
        Normalized agent name in lowercase with hyphens and -agent suffix
    """
    if not raw_name:
        return ""

    # Lowercase and strip
    name = raw_name.strip().lower()

    # Replace underscores and spaces with hyphens
    name = re.sub(r"[_\s]+", "-", name)

    # Remove duplicate hyphens
    name = re.sub(r"-+", "-", name)

    # Strip leading/trailing hyphens
    name = name.strip("-")

    # Ensure -agent suffix
    if not name.endswith("-agent"):
        # Handle case where name ends with just "agent" (no hyphen)
        if name.endswith("agent") and len(name) > 5:
            name = name[:-5].rstrip("-") + "-agent"
        elif name:
            name = f"{name}-agent"

    return name


def match_agent_name(normalized_name: str, available_agents: list[str]) -> Optional[str]:
    """Match normalized agent name against available agents list.

    Attempts exact match first, then tries normalizing available agents,
    then prefix matching for partial names.

    Args:
        normalized_name: Normalized agent name to match
        available_agents: List of available agent names

    Returns:
        Matched agent name from available_agents, or None if no match
    """
    if not normalized_name or not available_agents:
        return None

    # Exact match
    if normalized_name in available_agents:
        return normalized_name

    # Normalize available agents for comparison
    normalized_available = {normalize_agent_name(a): a for a in available_agents}
    if normalized_name in normalized_available:
        return normalized_available[normalized_name]

    # Prefix match (e.g., "tdd-red-agent" matches "tdd-red")
    base_name = normalized_name.replace("-agent", "")
    for avail_normalized, avail_original in normalized_available.items():
        avail_base = avail_normalized.replace("-agent", "")
        if base_name == avail_base:
            return avail_original

    return None


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
