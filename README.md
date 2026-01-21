# Ralphy

AI-powered code development tool based on Claude Code.

Ralphy transforms a PRD (Product Requirements Document) into a mergeable Pull Request through an autonomous loop with human validation at key stages.

## Installation

### Recommended: pipx

```bash
# Install pipx if needed
brew install pipx
pipx ensurepath

# Install Ralphy
pipx install -e /path/to/Ralphy/
```

### Alternative: uv (ultra-fast)

```bash
# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install Ralphy
uv tool install -e /path/to/Ralphy/
```

### For development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Prerequisites

- Python 3.11+
- Claude Code CLI installed and authenticated (`claude --version`)
- Git configured
- GitHub CLI (`gh`) authenticated for PR creation

## Limitations

- **Windows**: Not supported (technical limitation with `select()`)

## Usage

### Quick Start Mode (easiest)

Launch directly with a description - Ralphy creates everything automatically:

```bash
ralphy start "Add OAuth2 authentication with Google"
```

Ralphy will:
1. Derive a feature name: `add-oauth2-authentication-with-google`
2. Create the `docs/features/<feature>/` structure
3. Generate a minimal PRD from your description
4. Launch the complete workflow

### Standard Mode (existing PRD)

#### 1. Prepare the feature

Create the folder and PRD:

```bash
mkdir -p docs/features/my-feature
```

Create `docs/features/my-feature/PRD.md`:

```markdown
# My Feature

## Context
[Describe the context and problem to solve]

## Objective
[What the project should accomplish]

## Features
- Feature 1: description
- Feature 2: description

## Constraints
- Preferred tech stack
- Existing dependencies
- Time/performance constraints
```

#### 2. Launch the workflow

```bash
ralphy start my-feature
```

### Available commands

```bash
# Launch a workflow
ralphy start <feature>              # Start or resume the workflow
ralphy start <feature> --fresh      # Force a complete restart
ralphy start <feature> --no-progress # Disable real-time display

# Quick Start with description
ralphy start "Feature description"

# Status
ralphy status <feature>             # Status of a feature
ralphy status --all                 # Table of all features

# Control
ralphy abort <feature>              # Interrupt the running workflow
ralphy reset <feature>              # Reset state (confirmation required)

# Customization
ralphy init-prompts                 # Copy prompt templates for customization
ralphy init-prompts --force         # Overwrite existing prompts
```

## Workflow

```
PRD.md → [SPEC] → Validation → [DEV] → [QA] → Validation → [PR] → Done
```

| Phase | Agent | Output | Max Duration |
|-------|-------|--------|--------------|
| 1. SPECIFICATION | spec-agent | SPEC.md + TASKS.md | 30 min |
| 2. VALIDATION #1 | human | Approves specs | - |
| 3. IMPLEMENTATION | dev-agent | Code + tests | 4h |
| 4. QA | qa-agent | QA_REPORT.md | 30 min |
| 5. VALIDATION #2 | human | Approves QA report | - |
| 6. PR | pr-agent | GitHub Pull Request | 10 min |

### Human validations

**Validation #1 (specs)**: Verify that SPEC.md and TASKS.md match your expectations before implementation.

**Validation #2 (QA)**: Review the QA report before PR creation. The report lists detected quality/security issues.

### Automatic resume

If the workflow is interrupted (crash, timeout, rejection), simply relaunch:

```bash
ralphy start my-feature
```

Ralphy automatically resumes:
- **At phase level**: skips already completed phases (SPEC, DEV, QA)
- **At task level**: resumes from the last completed task in IMPLEMENTATION

### On rejection

If you reject at a validation, the workflow enters `REJECTED` state. To relaunch:

```bash
ralphy start my-feature
```

## Generated structure

```
my-project/
├── docs/features/
│   └── my-feature/
│       ├── PRD.md              # Your input (or generated in Quick Start)
│       ├── SPEC.md             # Specifications + architecture
│       ├── TASKS.md            # Ordered tasks
│       ├── QA_REPORT.md        # Quality/security report
│       └── .ralphy/
│           └── state.json      # Workflow state
├── .ralphy/
│   ├── config.yaml             # Global configuration (optional)
│   └── prompts/                # Custom prompts (optional)
├── src/                        # Generated code
└── tests/                      # Generated tests
```

## Configuration

Create `.ralphy/config.yaml` to customize (optional):

```yaml
project:
  name: my-project

models:
  specification: sonnet     # or opus, haiku
  implementation: opus      # most powerful model for implementation
  qa: sonnet
  pr: haiku                 # fast model for PR creation

stack:
  language: python          # or typescript, go, rust...
  test_command: pytest      # command to run tests

timeouts:
  specification: 1800       # 30 min
  implementation: 14400     # 4h
  qa: 1800                  # 30 min
  pr: 600                   # 10 min

retry:
  max_attempts: 2           # 1 = no retry
  delay_seconds: 5

circuit_breaker:
  enabled: true
  inactivity_timeout: 60    # seconds without output
  max_repeated_errors: 3    # same error repeated
  task_stagnation_timeout: 600  # 10 min without task completion
```

## Real-time display

During execution, Ralphy displays:
- **Task progress**: progress bar and task list
- **Current activity**: file reading, writing, tests, etc.
- **Tokens consumed**: input/output tokens and estimated cost in USD

Disable with `--no-progress` if you prefer raw logs.

## Tips for a good PRD

1. **Be precise** about expected features
2. **Specify the stack** if you have preferences
3. **List constraints** (performance, security, compatibility)
4. **Give examples** of usage if relevant
5. **Keep a reasonable scope** - one PRD = one PR

## License

MIT
