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
# Start workflow on a project
ralphy start /path/to/project

# Check workflow status
ralphy status /path/to/project

# Abort running workflow
ralphy abort /path/to/project

# Reset workflow state
ralphy reset /path/to/project
```

### Development Tools
```bash
# No linting configured (Python project without explicit linter in pyproject.toml)
# Manual code formatting recommended following PEP 8
```

## High-Level Architecture

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

#### BaseAgent (`ralphy/agents/base.py`)
Abstract base class for all agents implementing:
- **Retry logic**: Configurable retries on timeout/errors (not on EXIT_SIGNAL failures)
- **Circuit breaker integration**: Monitors agent execution for infinite loops/stagnation
- **Template-based prompts**: Loads prompts from `ralphy/prompts/*.md`
- **Exit signal detection**: Agents must emit `EXIT_SIGNAL: true` when complete

**Agent lifecycle**: `build_prompt()` → `ClaudeRunner.run()` → `parse_output()` → `AgentResult`

#### ClaudeRunner (`ralphy/claude.py`)
Subprocess wrapper for Claude Code CLI that:
- Executes `claude --print --dangerously-skip-permissions -p "..."`
- Streams output with **non-blocking I/O** (Unix `select()`, not Windows compatible)
- Supports abort via threading events (reactive within ~100ms)
- Integrates circuit breaker monitoring during execution
- Tracks process PID in `.ralphy/claude.pid` for external abort capability

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
Persistent workflow state in `.ralphy/state.json`:
- **Phase tracking**: Current workflow phase (IDLE → SPECIFICATION → ... → COMPLETED)
- **Task counters**: `tasks_completed` / `tasks_total` for progress display
- **Circuit breaker state**: Tracks attempts and last trigger
- **Valid transitions**: Enforced via `VALID_TRANSITIONS` dict to prevent invalid state changes

**Key methods**:
- `transition(new_phase)`: Validates and performs phase transitions
- `is_running()`: Checks if agent actively executing (not validation/completed states)
- `is_awaiting_validation()`: Detects validation gate states

### Agent Specialization

Each agent has a **specific prompt template** in `ralphy/prompts/`:

- **spec-agent**: Analyzes PRD, outputs architecture + ordered task list
- **dev-agent**: **Single long-running session** that processes all tasks sequentially, updates `TASKS.md` status, emits EXIT_SIGNAL when all tasks completed
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
Uses `rich` library for live terminal updates with task bars. Parses agent output for:
- Task completion markers (`completed`, `✓`, `done`, etc.)
- Updates progress bar and task list in real-time
- Integrates with logger's live mode to avoid output conflicts

### Validation Flow
`HumanValidator` (`ralphy/validation.py`) prompts user at two gates:
1. After spec generation: Shows `SPEC.md` and task count
2. After QA: Shows QA report summary with issue counts

User can `[Approve]` → continue or `[Reject]` → workflow enters REJECTED state.

## Project Structure Reference

```
ralphy/
├── agents/          # Specialized agents (spec, dev, qa, pr)
│   ├── base.py      # BaseAgent with retry + circuit breaker
│   ├── spec.py      # Specification generation
│   ├── dev.py       # Implementation (single long session)
│   ├── qa.py        # Quality assurance analysis
│   └── pr.py        # Pull request creation
├── prompts/         # Agent prompt templates (markdown)
│   ├── spec_agent.md
│   ├── dev_agent.md
│   ├── qa_agent.md
│   └── pr_agent.md
├── orchestrator.py  # Main workflow controller
├── state.py         # State machine + persistence
├── claude.py        # Claude Code CLI subprocess wrapper
├── circuit_breaker.py  # Infinite loop protection
├── config.py        # Configuration management
├── validation.py    # Human validation prompts
├── progress.py      # Terminal progress display
├── logger.py        # Structured logging
└── cli.py           # Click-based CLI commands

tests/               # Pytest test suite
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
- **Single workflow per project**: State tracked per project directory
- **No workflow persistence**: Interrupting Python process loses in-flight work (agent must complete)
- **Sequential phases**: Cannot run multiple agents in parallel

## Dependencies

Key external dependencies:
- `click`: CLI framework
- `pyyaml`: Config file parsing
- `rich`: Terminal formatting and progress display
- Claude Code CLI: Must be installed and authenticated (`claude --version`)
- Git + GitHub CLI (`gh`): For PR creation

## Troubleshooting

**Agent hangs/infinite loop**: Check circuit breaker logs for trigger detection. Increase timeout or adjust thresholds if legitimate long operation.

**EXIT_SIGNAL not detected**: Agent prompt must explicitly instruct to emit signal. Check prompt template includes exit signal instruction.

**State transition errors**: Check `VALID_TRANSITIONS` in `state.py`. May need to reset state with `ralphy reset`.

**Windows compatibility**: Use WSL or Linux. Native Windows support blocked by `select()` limitation.
