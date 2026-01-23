"""Development agent - Implements tasks defined in TASKS.md."""

import re
from pathlib import Path
from typing import Optional, Tuple

import yaml

from ralphy.agents.base import AgentResult, BaseAgent
from ralphy.claude import ClaudeResponse


class DevAgent(BaseAgent):
    """Agent that implements code according to TASKS.md."""

    name = "dev-agent"
    prompt_file = "dev_prompt.md"

    def build_prompt(self, start_from_task: Optional[str] = None) -> str:
        """Builds the prompt with specs and tasks.

        Args:
            start_from_task: Task ID to resume from (e.g., "1.8").
                             If provided, the agent will skip completed tasks.
        """
        template = self.load_prompt_template()
        if not template:
            self.logger.error("Template dev_prompt.md not found")
            return ""

        spec_content = self.read_feature_file("SPEC.md")
        if not spec_content:
            self.logger.error("SPEC.md not found in feature directory")
            return ""

        tasks_content = self.read_feature_file("TASKS.md")
        if not tasks_content:
            self.logger.error("TASKS.md not found in feature directory")
            return ""

        # Build resume instruction if resuming from a specific task
        resume_instruction = (
            self._build_resume_instruction(start_from_task)
            if start_from_task
            else ""
        )

        # Discover agents and build orchestration section
        discovered_agents = self._discover_agents()
        orchestration_section = self._build_orchestration_section(discovered_agents)

        return self._apply_placeholders(
            template,
            spec_content=spec_content,
            tasks_content=tasks_content,
            resume_instruction=resume_instruction,
            orchestration_section=orchestration_section,
        )

    def _build_resume_instruction(self, task_id: str) -> str:
        """Builds the resume instruction for the prompt."""
        return f"""
## RESUME MODE ACTIVE

**IMPORTANT**: You are resuming from a previous interrupted session.

- Skip all tasks BEFORE task {task_id} (they are already completed)
- Start directly with task {task_id}
- If task {task_id} has status `in_progress`, it was interrupted - reimplement it
- If task {task_id} has status `pending`, proceed normally
- Continue sequentially until the end
- DO NOT reimplement tasks marked as `completed`

Verify: Before starting, read `TASKS.md` and confirm that tasks before {task_id} are `completed`.
"""

    def _discover_agents(self) -> list[dict[str, str]]:
        """Discover Claude Code agents in .claude/agents/ directory."""
        agents_dir = self.project_path / ".claude" / "agents"

        if not agents_dir.exists() or not agents_dir.is_dir():
            self.logger.info("No agents found, using direct implementation")
            return []

        agents = []
        for agent_file in agents_dir.glob("*.md"):
            agent_info = self._parse_agent_file(agent_file)
            if agent_info:
                agents.append(agent_info)

        if agents:
            self.logger.info(
                f"Discovered {len(agents)} agents: {[a['name'] for a in agents]}"
            )
        else:
            self.logger.info("No agents found, using direct implementation")

        return agents

    def _parse_agent_file(self, filepath: Path) -> dict[str, str] | None:
        """Parse agent file and extract name/description from frontmatter."""
        try:
            content = filepath.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None

        if not content.startswith("---"):
            return None

        end_idx = content.find("---", 3)
        if end_idx == -1:
            return None

        try:
            frontmatter = yaml.safe_load(content[3:end_idx].strip())
        except yaml.YAMLError:
            return None

        if not isinstance(frontmatter, dict):
            return None

        name = frontmatter.get("name")
        description = frontmatter.get("description")

        if not name or not description:
            return None

        return {"name": str(name), "description": str(description)}

    def _format_agents_list(self, agents: list[dict[str, str]]) -> str:
        """Format agents as markdown list."""
        if not agents:
            return ""
        return "\n".join(f"- **{a['name']}**: {a['description']}" for a in agents)

    def _build_orchestration_section(self, agents: list[dict[str, str]]) -> str:
        """Build orchestration instructions when agents are available."""
        if not agents:
            return ""

        agents_list = self._format_agents_list(agents)
        return f"""
## Agent Orchestration

You have access to specialized agents. Delegate task groups to appropriate agents using the Task tool.

### Available Agents

{agents_list}

### Delegation Guidelines

1. **Analyze tasks** - Group related tasks (e.g., all model tasks, all controller tasks)
2. **Match by capability** - Choose agent whose description aligns with task type
3. **Delegate via Task tool** - Invoke with clear instructions
4. **Verify completion** - Ensure agent completed work successfully

### When NOT to Delegate

- Simple tasks that don't match any agent's specialty
- Tasks requiring cross-cutting changes
- When you can implement more efficiently yourself

You remain responsible for TASKS.md updates and overall completion.
"""

    def parse_output(self, response: ClaudeResponse) -> AgentResult:
        """Verifies that tasks have been implemented."""
        completed, total = self.count_task_status()
        files_generated = self._detect_generated_files()

        if completed < total:
            return AgentResult(
                success=False,
                output=response.output,
                files_generated=files_generated,
                error_message=f"Incomplete tasks: {completed}/{total}",
            )

        return AgentResult(
            success=response.exit_signal,
            output=response.output,
            files_generated=files_generated,
            error_message=None if response.exit_signal else "EXIT_SIGNAL not received",
        )

    def count_task_status(self) -> Tuple[int, int]:
        """Counts completed tasks and total."""
        tasks_content = self.read_feature_file("TASKS.md")
        if not tasks_content:
            return 0, 0

        # Count total tasks (format: ### Task X.Y or ## Task X)
        total = len(re.findall(r"#{2,3}\s*Task\s*[\d.]+", tasks_content, re.IGNORECASE))
        # Count completed tasks
        completed = len(re.findall(r"\*\*Status\*\*:\s*completed", tasks_content, re.IGNORECASE))

        return completed, total

    def get_in_progress_task(self) -> str | None:
        """Returns the ID of the in_progress task if there is one."""
        tasks_content = self.read_feature_file("TASKS.md")
        if not tasks_content:
            return None

        # Search for task with in_progress status
        # Format: ### Task 1.9: [Title]\n- **Status**: in_progress
        pattern = r"#{2,3}\s*Task\s*([\d.]+)[^\n]*\n[^#]*\*\*Status\*\*:\s*in_progress"
        match = re.search(pattern, tasks_content, re.IGNORECASE)
        if match:
            return match.group(1)
        return None

    def get_next_pending_task_after(self, task_id: str) -> Optional[str]:
        """Finds the next pending task after a given ID.

        Used during resume: if task_id is completed, find the next one.

        Args:
            task_id: ID of the last known task (e.g., "1.5")

        Returns:
            ID of the next non-completed task, or None if all completed
        """
        tasks_content = self.read_feature_file("TASKS.md")
        if not tasks_content:
            return None

        # Pattern to extract task ID and status
        # Format: ### Task 1.9: [Title]\n- **Status**: pending
        pattern = r"#{2,3}\s*Task\s*([\d.]+)[^\n]*\n[^#]*\*\*Status\*\*:\s*(\w+)"
        matches = re.findall(pattern, tasks_content, re.IGNORECASE)

        found_target = False
        for tid, status in matches:
            if tid == task_id:
                found_target = True
                # If this task is not completed, return it
                if status.lower() != "completed":
                    return tid
            elif found_target and status.lower() != "completed":
                # Found first non-completed task after target
                return tid

        return None

    def _detect_generated_files(self) -> list[str]:
        """Detects generated files in src/ and tests/ directories."""
        files = []

        src_dir = self.project_path / "src"
        if src_dir.exists():
            for f in src_dir.rglob("*"):
                if f.is_file():
                    files.append(str(f.relative_to(self.project_path)))

        tests_dir = self.project_path / "tests"
        if tests_dir.exists():
            for f in tests_dir.rglob("*"):
                if f.is_file() and f.name != "__init__.py":
                    files.append(str(f.relative_to(self.project_path)))

        return files
