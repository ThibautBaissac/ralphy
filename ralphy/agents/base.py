"""Base class for Ralphy agents."""

from __future__ import annotations

import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import TYPE_CHECKING, Callable, ClassVar, Optional

from ralphy.circuit_breaker import CircuitBreaker, CircuitBreakerContext
from ralphy.claude import ClaudeResponse, ClaudeRunner
from ralphy.config import ProjectConfig
from ralphy.constants import MIN_PROMPT_SIZE_CHARS
from ralphy.logger import get_logger
from ralphy.state import Phase

if TYPE_CHECKING:
    from ralphy.claude import TokenUsage


@dataclass
class AgentResult:
    """Result of agent execution."""

    success: bool
    output: str
    files_generated: list[str]
    error_message: Optional[str] = None


class BaseAgent(ABC):
    """Abstract base class for all agents."""

    name: str = "base-agent"
    prompt_file: str = ""

    # Class-level prompt cache to avoid repeated disk I/O
    _prompt_cache: ClassVar[dict[tuple[Path, str], str]] = {}
    _cache_lock: ClassVar[threading.Lock] = threading.Lock()

    def __init__(
        self,
        project_path: Path,
        config: ProjectConfig,
        on_output: Optional[Callable[[str], None]] = None,
        model: Optional[str] = None,
        feature_dir: Optional[Path] = None,
        on_token_update: Optional[Callable[[TokenUsage, float], None]] = None,
    ):
        self.project_path = project_path
        self.config = config
        self.on_output = on_output
        self.model = model
        self.feature_dir = feature_dir
        self.on_token_update = on_token_update
        self.logger = get_logger()

    @abstractmethod
    def build_prompt(self) -> str:
        """Builds the prompt for the agent."""
        pass

    @abstractmethod
    def parse_output(self, response: ClaudeResponse) -> AgentResult:
        """Parses Claude's output and returns the result."""
        pass

    def load_prompt_template(self) -> str:
        """Load prompt template from project or package.

        Priority order:
        1. .claude/agents/{prompt_file} (project custom)
        2. ralphy/templates/agents/{prompt_file} (package default)

        Custom prompts are validated before use. If invalid, the default
        template is used with a warning. YAML frontmatter is stripped.

        Results are cached at the class level to avoid repeated disk I/O.
        """
        cache_key = (self.project_path, self.prompt_file)

        # Check cache first (under lock for thread safety)
        with self._cache_lock:
            if cache_key in self._prompt_cache:
                return self._prompt_cache[cache_key]

        # Load from disk
        content = self._load_prompt_from_disk()

        # Cache the result
        with self._cache_lock:
            self._prompt_cache[cache_key] = content

        return content

    def _load_prompt_from_disk(self) -> str:
        """Load prompt template from disk (custom or package default).

        Priority order:
        1. .claude/agents/{prompt_file} (project custom)
        2. ralphy/templates/agents/{prompt_file} (package default)

        Custom prompts are validated before use. If invalid, the default
        template is used with a warning. YAML frontmatter is stripped
        from the loaded content.
        """
        # 1. Look in the project (.claude/agents/)
        local_path = self.project_path / ".claude" / "agents" / self.prompt_file
        if local_path.exists():
            content = local_path.read_text(encoding="utf-8")
            if self._validate_prompt(content):
                return self._strip_frontmatter(content)
            self.logger.warn(f"Custom prompt {self.prompt_file} invalid, using default")

        # 2. Fallback to package (ralphy/templates/agents/)
        try:
            content = resources.files("ralphy.templates.agents").joinpath(self.prompt_file).read_text(encoding="utf-8")
            return self._strip_frontmatter(content)
        except (FileNotFoundError, TypeError):
            self.logger.error(f"Template {self.prompt_file} not found")
            return ""

    def _strip_frontmatter(self, content: str) -> str:
        """Strip YAML frontmatter from content if present.

        YAML frontmatter is delimited by '---' at the start and end.
        This is used for agent metadata (name, description, triggers)
        but should not be included in the final prompt.

        Args:
            content: The template content, potentially with frontmatter.

        Returns:
            Content with frontmatter removed, leading whitespace stripped.
        """
        if not content.startswith("---"):
            return content
        end_idx = content.find("---", 3)
        if end_idx == -1:
            return content
        return content[end_idx + 3:].lstrip()

    @classmethod
    def clear_prompt_cache(cls) -> None:
        """Clear the prompt template cache.

        Useful for testing or when prompt files are modified during runtime.
        """
        with cls._cache_lock:
            cls._prompt_cache.clear()

    def _apply_common_placeholders(self, template: str) -> str:
        """Replace common placeholders in a template.

        Replaces:
        - {{project_name}}: Project name from config
        - {{language}}: Stack language from config
        - {{test_command}}: Test command from config
        - {{feature_path}}: Relative path to feature directory (e.g., "docs/features/my-feature")

        Args:
            template: The template string with placeholders.

        Returns:
            Template with common placeholders replaced.
        """
        result = template.replace("{{project_name}}", self.config.name)
        result = result.replace("{{language}}", self.config.stack.language)
        result = result.replace("{{test_command}}", self.config.stack.test_command)
        # Feature path relative to project root
        if self.feature_dir:
            try:
                feature_path = str(self.feature_dir.relative_to(self.project_path))
            except ValueError:
                # feature_dir is not relative to project_path, use absolute
                feature_path = str(self.feature_dir)
        else:
            feature_path = ""
        result = result.replace("{{feature_path}}", feature_path)
        result = result.replace("{{tdd_instructions}}", self._get_tdd_instructions())
        return result

    def _apply_placeholders(self, template: str, **kwargs: str) -> str:
        """Apply common placeholders plus custom key-value pairs.

        First applies common placeholders (project_name, language, test_command),
        then replaces any additional {{key}} patterns with provided values.

        Args:
            template: The template string with placeholders.
            **kwargs: Additional placeholder key-value pairs (e.g., prd_content="...").
                      None values are replaced with empty strings.

        Returns:
            Template with all placeholders replaced.
        """
        result = self._apply_common_placeholders(template)
        for key, value in kwargs.items():
            result = result.replace(f"{{{{{key}}}}}", value or "")
        return result

    def _validate_prompt(self, content: str) -> bool:
        """Validates that a custom prompt is usable.

        Checks:
        - Non-empty content with minimum MIN_PROMPT_SIZE_CHARS characters
        - Contains EXIT_SIGNAL instruction (required for all agents)

        Args:
            content: Prompt content to validate.

        Returns:
            True if prompt is valid, False otherwise.
        """
        if not content or len(content) < MIN_PROMPT_SIZE_CHARS:
            self.logger.warn(f"Custom prompt is empty or too short (< {MIN_PROMPT_SIZE_CHARS} chars)")
            return False
        if "EXIT_SIGNAL" not in content:
            self.logger.warn("Custom prompt missing EXIT_SIGNAL instruction")
            return False
        return True

    def _get_tdd_instructions(self) -> str:
        """Return TDD workflow instructions based on heuristics.

        TDD is recommended for certain task types:
        - New features with business logic
        - Bug fixes (test reproduces the bug first)
        - Refactoring (tests ensure behavior preserved)

        TDD is less beneficial for:
        - Configuration changes
        - Simple UI adjustments
        - Documentation updates
        - Migration scripts

        Returns:
            TDD instructions string with heuristics for when to apply TDD.
        """
        return """
## TDD Workflow Guidelines

For tasks that benefit from TDD, follow the RED -> GREEN -> REFACTOR cycle:

### When to Use TDD

**TDD-Friendly Tasks** (write tests first):
- New features with business logic
- Bug fixes (test reproduces the bug first)
- Refactoring (tests ensure behavior preserved)
- API endpoints and data transformations

**Non-TDD Tasks** (implement directly):
- Configuration changes
- Simple UI adjustments
- Documentation updates
- Migration scripts
- Dependency updates

### The TDD Cycle

#### 1. RED: Write Failing Test First
- Create test that defines expected behavior
- Run test - verify it FAILS
- This confirms the test actually tests something

#### 2. GREEN: Implement Minimal Code
- Write minimum code to make test pass
- Don't add extra features yet
- Run test - verify it PASSES

#### 3. REFACTOR: Improve Code Quality
- Clean up while keeping tests green
- Remove duplication, improve naming
- Run tests after each change

### Per-Task Override

If a task in TASKS.md specifies `- **TDD**: true` or `- **TDD**: false`, follow that directive. Otherwise, use your judgment based on the task type.

### TDD Best Practices
- Keep the RED-GREEN cycle short (minutes, not hours)
- One test at a time: write one test, make it pass, repeat
- Test behavior, not implementation details
"""

    def read_file(self, filename: str) -> Optional[str]:
        """Reads a file from the project."""
        filepath = self.project_path / filename
        if filepath.exists():
            return filepath.read_text(encoding="utf-8")
        return None

    def read_feature_file(self, filename: str) -> Optional[str]:
        """Read a file from the feature directory.

        Args:
            filename: Name of the file to read (e.g., "PRD.md", "SPEC.md")

        Returns:
            File content as string, or None if file doesn't exist or no feature_dir
        """
        if not self.feature_dir:
            return None
        filepath = self.feature_dir / filename
        if filepath.exists():
            return filepath.read_text(encoding="utf-8")
        return None

    def run(
        self,
        timeout: Optional[int] = None,
        phase: Optional[Phase] = None,
        **prompt_kwargs,
    ) -> AgentResult:
        """Runs the agent with automatic retry and circuit breaker.

        Args:
            timeout: Timeout in seconds. If not specified, uses
                     config.timeouts.agent as fallback.
            phase: Workflow phase for circuit breaker context.
            **prompt_kwargs: Additional arguments passed to build_prompt().

        Returns:
            AgentResult with execution results.

        Retry is triggered on timeout, error (return code != 0),
        or circuit breaker triggered.
        The number of attempts and delay are configurable via
        config.retry.max_attempts and config.retry.delay_seconds.
        """
        self.logger.agent(self.name, "started")

        prompt = self.build_prompt(**prompt_kwargs)
        if not prompt:
            return AgentResult(
                success=False,
                output="",
                files_generated=[],
                error_message="Failed to build prompt",
            )

        # Use specific timeout or agent fallback
        agent_timeout = timeout or self.config.timeouts.agent
        max_attempts = self.config.retry.max_attempts
        delay = self.config.retry.delay_seconds

        # Circuit breaker configuration
        cb_config = self.config.circuit_breaker
        cb_context = CircuitBreakerContext(
            phase=phase or Phase.IMPLEMENTATION,
            is_dev_agent=(self.name == "dev-agent"),
            test_command=self.config.stack.test_command,
        )

        last_response: Optional[ClaudeResponse] = None
        last_error: Optional[str] = None

        for attempt in range(1, max_attempts + 1):
            if attempt > 1:
                self.logger.agent(self.name, f"retry {attempt}/{max_attempts}")
                time.sleep(delay)

            # Create circuit breaker if enabled (reset on each attempt)
            circuit_breaker = None
            if cb_config.enabled:
                circuit_breaker = CircuitBreaker(
                    config=cb_config,
                    context=cb_context,
                    on_warning=lambda t, a: self.logger.warn(
                        f"Circuit breaker: {t.value} ({a}/{cb_config.max_attempts})"
                    ),
                    on_trip=lambda t: self.logger.error(
                        f"Circuit breaker: OPEN - {t.value}"
                    ),
                )

            runner = ClaudeRunner(
                working_dir=self.project_path,
                timeout=agent_timeout,
                on_output=self.on_output,
                circuit_breaker=circuit_breaker,
                model=self.model,
                on_token_update=self.on_token_update,
            )

            response = runner.run(prompt)
            last_response = response

            # Circuit breaker triggered - retry possible
            if response.circuit_breaker_triggered:
                trigger_type = (
                    circuit_breaker.last_trigger.value
                    if circuit_breaker and circuit_breaker.last_trigger
                    else "unknown"
                )
                last_error = f"Circuit breaker: {trigger_type}"
                if attempt < max_attempts:
                    self.logger.warn(f"{self.name}: {last_error}, retry...")
                    continue
                self.logger.agent(self.name, "circuit_breaker_open")
                return AgentResult(
                    success=False,
                    output=response.output,
                    files_generated=[],
                    error_message=last_error,
                )

            # Timeout - retry possible
            if response.timed_out:
                last_error = f"Timeout after {agent_timeout}s"
                if attempt < max_attempts:
                    self.logger.warn(f"{self.name}: {last_error}, retry...")
                    continue
                self.logger.agent(self.name, "timeout")
                return AgentResult(
                    success=False,
                    output=response.output,
                    files_generated=[],
                    error_message=last_error,
                )

            # Claude error - retry possible
            if response.return_code != 0:
                last_error = f"Return code: {response.return_code}"
                if attempt < max_attempts:
                    self.logger.warn(f"{self.name}: {last_error}, retry...")
                    continue
                self.logger.agent(self.name, "failed")
                return AgentResult(
                    success=False,
                    output=response.output,
                    files_generated=[],
                    error_message=last_error,
                )

            # Claude responded correctly - no retry needed
            break

        # Parse result (no retry on parsing/EXIT_SIGNAL failure)
        result = self.parse_output(last_response)

        if result.success:
            self.logger.agent(self.name, "completed")
        else:
            self.logger.agent(self.name, f"failed: {result.error_message}")

        return result
