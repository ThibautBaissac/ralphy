# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Ralphy is an AI-powered development automation tool that transforms a Product Requirements Document (PRD) into a mergeable Pull Request through an autonomous workflow with human validation at key stages. It orchestrates Claude Code CLI through multiple specialized agents to handle specification, implementation, quality assurance, and PR creation.

## Development Commands

### Setup and Installation

For development (contributing to Ralphy):
```bash
# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install in development mode with dependencies
pip install -e ".[dev]"

# Verify installation
ralphy --version
```

For usage (installing as a CLI tool):
```bash
# Option 1: pipx (recommended for CLI tools)
pipx install -e /path/to/Ralphy/

# Option 2: uv (fastest)
uv tool install -e /path/to/Ralphy/
```

### Testing
```bash
# Run all tests
pytest

# Run tests with coverage
pytest --cov=ralphy

# Run specific test file
pytest tests/test_orchestrator.py

# Run specific test function
pytest tests/test_circuit_breaker.py::test_inactivity_trigger
```

### Running Ralphy
```bash
# Start workflow for a feature (PRD must exist at docs/features/<feature>/PRD.md)
ralphy start my-feature

# Quick Start Mode: Create feature from description (auto-generates PRD)
ralphy start "Add user authentication with OAuth2"

# Start with fresh state (ignore existing progress)
ralphy start my-feature --fresh

# Disable live progress display
ralphy start my-feature --no-progress

# Check workflow status for a specific feature
ralphy status my-feature

# Check status of all features
ralphy status --all

# Abort running workflow
ralphy abort my-feature

# Reset workflow state
ralphy reset my-feature

# Initialize custom prompt templates
ralphy init-prompts /path/to/project
```

### Development Tools
```bash
# No linting configured (Python project without explicit linter in pyproject.toml)
# Manual code formatting recommended following PEP 8
```

## High-Level Architecture

### Feature-Based Workflow

Ralphy organizes work by **features**, with each feature having its own directory structure:

```
docs/features/<feature-name>/
├── PRD.md              # Product Requirements Document (input)
├── SPEC.md             # Generated specification
├── TASKS.md            # Generated task list
├── QA_REPORT.md        # Quality analysis report
└── .ralphy/
    ├── state.json      # Feature-specific workflow state
    ├── config.yaml     # Optional feature-specific config
    └── prompts/        # Optional custom prompts
```

**Feature naming**: Must match pattern `^[a-zA-Z0-9][a-zA-Z0-9_-]*$`

### Quick Start Mode

When you provide a description instead of a feature name, Ralphy automatically:
1. Derives a feature name from the description (e.g., "Add user auth" → `add-user-auth`)
2. Creates the feature directory structure
3. Generates a minimal `PRD.md` from your description
4. Starts the workflow

```bash
# These are equivalent:
ralphy start "Implement dark mode toggle"
# Creates feature: implement-dark-mode-toggle with auto-generated PRD
```

### Workflow Orchestration

Ralphy implements a **state machine-based workflow** with 4 distinct phases:

1. **SPECIFICATION** (spec-agent): Generates `SPEC.md` + `TASKS.md` from `PRD.md`
2. **IMPLEMENTATION** (dev-agent): Implements all tasks in one long-running Claude session
3. **QA** (qa-agent): Analyzes code quality and security, produces `QA_REPORT.md`
4. **PR** (pr-agent): Creates GitHub Pull Request via `gh` CLI

**Human validation gates** occur after SPECIFICATION and QA phases. The workflow cannot proceed without explicit approval.

### Key Architectural Components

#### Orchestrator (`ralphy/orchestrator.py`)
Central workflow controller that:
- Manages phase transitions via `StateManager`
- Runs agents with timeout enforcement
- Handles human validation prompts via `HumanValidator`
- Coordinates progress display and output streaming
- Enforces valid state transitions (defined in `state.py::VALID_TRANSITIONS`)
- **Smart resume**: Skips already-completed phases and validates artifacts before resuming
- **Task-level checkpointing**: Tracks `last_completed_task_id` for mid-implementation resume

#### BaseAgent (`ralphy/agents/base.py`)
Abstract base class for all agents implementing:
- **Retry logic**: Configurable retries on timeout/errors (not on EXIT_SIGNAL failures)
- **Circuit breaker integration**: Monitors agent execution for infinite loops/stagnation
- **Template-based prompts**: Loads prompts from `ralphy/prompts/*.md`
- **Exit signal detection**: Agents must emit `EXIT_SIGNAL: true` when complete
- **Token usage tracking**: Callbacks for real-time token consumption monitoring

**Agent lifecycle**: `build_prompt()` → `ClaudeRunner.run()` → `parse_output()` → `AgentResult`

#### ClaudeRunner (`ralphy/claude.py`)
Subprocess wrapper for Claude Code CLI that:
- Executes `claude --print --dangerously-skip-permissions --output-format stream-json -p "..."`
- Uses **stream-json output format** for real-time token tracking
- Streams output with **non-blocking I/O** (Unix `select()`, not Windows compatible)
- Supports abort via threading events (reactive within ~100ms)
- Integrates circuit breaker monitoring during execution
- Tracks process PID in `.ralphy/claude.pid` for external abort capability

**Token Usage Tracking**:
- `TokenUsage` dataclass tracks input/output tokens, cache read/creation
- `ClaudeResponse` includes `token_usage` and `total_cost_usd`
- `JsonStreamParser` extracts text and usage data from stream-json format

**Critical**: Uses `subprocess.Popen` with unbuffered text mode for real-time output processing.

#### Circuit Breaker (`ralphy/circuit_breaker.py`)
Protection mechanism against infinite loops with 4 trigger types:

| Trigger | Default Threshold | Scope |
|---------|------------------|-------|
| `INACTIVITY` | 60s no output | All agents |
| `REPEATED_ERROR` | 3x same error hash | All agents |
| `TASK_STAGNATION` | 10 min no task completion | dev-agent only |
| `OUTPUT_SIZE` | 500 KB cumulative | All agents |

**State progression**: `CLOSED` → warnings (attempts 1-2) → `OPEN` (attempt 3, kills process)

**Thread safety**: Uses `threading.Lock` for all state mutations. Callbacks invoked **outside lock** to prevent deadlocks.

**Special timeout adjustments**:
- PR phase: 120s inactivity (slow git operations)
- Test command detected: 300s inactivity (long-running tests)

#### State Management (`ralphy/state.py`)
Persistent workflow state in `docs/features/<feature>/.ralphy/state.json`:
- **Phase tracking**: Current workflow phase (IDLE → SPECIFICATION → ... → COMPLETED)
- **Task counters**: `tasks_completed` / `tasks_total` for progress display
- **Circuit breaker state**: Tracks attempts and last trigger
- **Valid transitions**: Enforced via `VALID_TRANSITIONS` dict to prevent invalid state changes
- **Resume checkpoint**: `last_completed_phase`, `last_completed_task_id`, `last_in_progress_task_id`
- **Task checkpoint time**: ISO timestamp for resume tracking

**Key methods**:
- `transition(new_phase)`: Validates and performs phase transitions
- `checkpoint_task(task_id)`: Saves task progress for resume capability
- `mark_phase_completed(phase)`: Records phase completion for resume logic
- `get_resume_task_id()`: Returns task to resume from after interruption
- `is_running()`: Checks if agent actively executing (not validation/completed states)
- `is_awaiting_validation()`: Detects validation gate states

### Agent Specialization

Each agent has a **specific prompt template** in `ralphy/prompts/`:

- **spec-agent**: Analyzes PRD, outputs architecture + ordered task list
- **dev-agent**: **Single long-running session** that processes all tasks sequentially, updates `TASKS.md` status, emits EXIT_SIGNAL when all tasks completed
  - Supports **task resume**: receives `{{resume_instruction}}` with specific task to continue from
  - Methods: `count_task_status()`, `get_in_progress_task()`, `get_next_pending_task_after()`
- **qa-agent**: Code quality/security analysis (OWASP Top 10), structured report
- **pr-agent**: Git branch creation, commit, push, `gh pr create`

**Important**: The dev-agent is designed as **one invocation** that handles all tasks. It's not a loop of multiple invocations per task.

### Configuration System (`ralphy/config.py`)

Hierarchical config from `.ralphy/config.yaml`:

```python
ProjectConfig
  ├── TimeoutConfig      # Per-phase timeouts (spec: 30min, impl: 4h, qa: 30min, pr: 10min)
  ├── ModelConfig        # Per-phase Claude models (specification, implementation, qa, pr)
  ├── StackConfig        # language, test_command
  ├── RetryConfig        # max_attempts, delay_seconds
  └── CircuitBreakerConfig  # All trigger thresholds
```

**Defaults are sensible** - most projects don't need custom config. Only specify when needed.

**Model selection**: Each phase can use a different Claude model. The model is passed to Claude Code CLI via `--model <model>` flag. This allows cost/performance optimization (e.g., use `opus` for complex implementation, `haiku` for simple PR creation).

**Model validation**: A whitelist of allowed models prevents command injection via config. Supported values: `sonnet`, `opus`, `haiku`, or full model names like `claude-opus-4-5-20251101`. Invalid models fall back to `sonnet`.

## Critical Implementation Details

### Exit Signal Protocol
All agents must emit `EXIT_SIGNAL: true` in their output to signal completion. This is the **primary success indicator**, not just return code. Agents can succeed (return code 0) but fail validation if EXIT_SIGNAL is missing.

### Thread Safety in ClaudeRunner
The abort mechanism uses `threading.Event` with periodic checks:
- Main thread: waits on process with `ABORT_CHECK_INTERVAL` timeout
- Reader thread: reads stdout non-blocking via `select()`, checks abort event
- CB monitor thread: checks task stagnation every second

**All threads** respect `_abort_event.is_set()` for coordinated shutdown.

### Progress Display (`ralphy/progress.py`)
Uses `rich` library for live terminal updates with task bars. Features:
- Task completion markers (`completed`, `✓`, `done`, etc.)
- Updates progress bar and task list in real-time
- Integrates with logger's live mode to avoid output conflicts
- **Token usage display**: Shows input/output tokens and cost in USD
- **Activity detection**: Parses output for specific patterns:
  - TASK_START/TASK_COMPLETE (e.g., task IDs like "1.7", "2.3")
  - WRITING_FILE, RUNNING_TEST, RUNNING_COMMAND
  - READING_FILE, THINKING
- **OutputParser class**: Extracts task info and emits callbacks

### Validation Flow
`HumanValidator` (`ralphy/validation.py`) prompts user at two gates:
1. After spec generation: Shows `SPEC.md` and task count
2. After QA: Shows QA report summary with issue counts

User can `[Approve]` → continue or `[Reject]` → workflow enters REJECTED state.

### Task Resume System

When a workflow is interrupted or fails, Ralphy can resume from the exact point of failure:

1. **Phase-level resume**: Skips completed phases (SPECIFICATION, IMPLEMENTATION, QA)
2. **Task-level resume**: For IMPLEMENTATION phase, resumes from the last completed task
3. **Artifact validation**: Before resuming, validates that required files exist (SPEC.md, TASKS.md)

**Resume flow**:
1. `_determine_resume_phase()` checks `last_completed_phase` in state
2. `_should_skip_phase()` compares current phase with resume point
3. `_restore_task_count()` restores progress counters
4. Dev agent receives `{{resume_instruction}}` with specific task ID

## Project Structure Reference

```
ralphy/
├── agents/          # Specialized agents (spec, dev, qa, pr)
│   ├── base.py      # BaseAgent with retry + circuit breaker + token tracking
│   ├── spec.py      # Specification generation
│   ├── dev.py       # Implementation (single long session) + task resume
│   ├── qa.py        # Quality assurance analysis
│   └── pr.py        # Pull request creation
├── prompts/         # Agent prompt templates (markdown)
│   ├── spec_agent.md
│   ├── dev_agent.md
│   ├── qa_agent.md
│   └── pr_agent.md
├── orchestrator.py  # Main workflow controller + resume logic
├── state.py         # State machine + persistence + checkpointing
├── claude.py        # Claude Code CLI subprocess wrapper + token tracking
├── circuit_breaker.py  # Infinite loop protection
├── config.py        # Configuration management + model validation
├── validation.py    # Human validation prompts
├── progress.py      # Terminal progress display + activity detection
├── logger.py        # Structured logging
└── cli.py           # Click-based CLI commands + quick start

tests/               # Pytest test suite (8 test files)
├── test_cli.py
├── test_agents.py
├── test_circuit_breaker.py
├── test_state.py
├── test_orchestrator.py
├── test_config.py
├── test_claude.py
└── test_progress.py
```

## Common Patterns

### Adding a New Agent
1. Create `ralphy/agents/your_agent.py` extending `BaseAgent`
2. Implement `build_prompt()` to construct prompt from template
3. Implement `parse_output(response)` to validate EXIT_SIGNAL and extract results
4. Add prompt template to `ralphy/prompts/your_agent.md`
5. Wire into orchestrator phase method

### Modifying Timeouts
Edit `.ralphy/config.yaml` in target project:
```yaml
timeouts:
  implementation: 7200  # 2 hours instead of default 4
```

### Configuring Models per Phase
Specify different Claude models for each phase in `.ralphy/config.yaml`:
```yaml
models:
  specification: sonnet    # Fast, good for spec generation
  implementation: opus     # Most capable for complex implementation
  qa: sonnet              # Good balance for QA analysis
  pr: haiku               # Fast, simple PR creation
```

Supported values: `sonnet`, `opus`, `haiku`, or full model names like `claude-sonnet-4-5-20250929`.
Default: All phases use `sonnet` if not specified.

### Custom Prompt Templates

Ralphy supports custom prompts to adapt agent behavior for your tech stack. Prompts are loaded with priority:
1. `.ralphy/prompts/{agent}.md` (project-specific)
2. `ralphy/prompts/{agent}.md` (package defaults)

**Initialize custom prompts:**
```bash
# Copy default prompts to your project
ralphy init-prompts /path/to/project

# Overwrite existing custom prompts
ralphy init-prompts --force /path/to/project
```

This creates `.ralphy/prompts/` with all 4 agent templates:
- `spec_agent.md` - Specification generation
- `dev_agent.md` - Implementation
- `qa_agent.md` - Quality assurance
- `pr_agent.md` - Pull request creation

**Available placeholders** (replaced at runtime):

| Placeholder | Description | Agents |
|-------------|-------------|--------|
| `{{project_name}}` | Project name | All |
| `{{language}}` | Tech stack from config | All |
| `{{test_command}}` | Test command from config | spec, dev |
| `{{prd_content}}` | PRD.md content | spec |
| `{{spec_content}}` | SPEC.md content | dev, qa, pr |
| `{{tasks_content}}` | TASKS.md content | dev |
| `{{resume_instruction}}` | Resume instructions | dev |
| `{{branch_name}}` | Branch name | pr |
| `{{qa_report}}` | QA report content | pr |

**Requirements for custom prompts:**
- Must contain `EXIT_SIGNAL` instruction (required for agent completion detection)
- Must be at least 100 characters long
- Invalid prompts fall back to defaults with a warning

### Adding Circuit Breaker Trigger
1. Add trigger type to `TriggerType` enum in `circuit_breaker.py`
2. Implement detection method (e.g., `_check_new_trigger()`)
3. Call from `record_output()` or create monitoring method
4. Add config parameter to `CircuitBreakerConfig`

## Testing Notes

- **Unit tests** mock `ClaudeRunner` to avoid actual subprocess calls
- **Circuit breaker tests** use time-based scenarios with controlled output
- **State tests** verify valid/invalid transition enforcement
- **Integration tests** would require Claude Code CLI (not in test suite)

## Limitations

- **Windows not supported**: Uses Unix `select()` for non-blocking I/O
- **Sequential phases**: Cannot run multiple agents in parallel
- **No mid-task persistence**: Task checkpointing saves task ID, but work within a task may be lost on interrupt

## Dependencies

Key external dependencies:
- `click`: CLI framework
- `psutil`: Process management (for circuit breaker)
- `pyyaml`: Config file parsing
- `rich`: Terminal formatting and progress display
- Claude Code CLI: Must be installed and authenticated (`claude --version`)
- Git + GitHub CLI (`gh`): For PR creation

## Troubleshooting

**Agent hangs/infinite loop**: Check circuit breaker logs for trigger detection. Increase timeout or adjust thresholds if legitimate long operation.

**EXIT_SIGNAL not detected**: Agent prompt must explicitly instruct to emit signal. Check prompt template includes exit signal instruction.

**State transition errors**: Check `VALID_TRANSITIONS` in `state.py`. May need to reset state with `ralphy reset <feature>`.

**Windows compatibility**: Use WSL or Linux. Native Windows support blocked by `select()` limitation.

**Resume not working**: Verify artifact files exist (SPEC.md, TASKS.md). Check `state.json` for `last_completed_phase` value.
