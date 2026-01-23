# Ralphy

Ralphy transforms a feature description into a mergeable Pull Request. It orchestrates Claude Code through specialized agents that handle specification, implementation, QA, and PR creation - with human validation at key stages.

## Quick Start

```bash
# Install (pick one)
pipx install -e /path/to/Ralphy/    # recommended
uv tool install -e /path/to/Ralphy/ # faster alternative

# Run with just a description
ralphy start "Add user authentication with OAuth2"
```

That's it. Ralphy will generate specs, implement code, run QA, and create a PR.

## Prerequisites

- Python 3.11+
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) installed and authenticated
- Git configured
- GitHub CLI (`gh`) authenticated

**Note**: Windows is not supported.

## Two Ways to Use Ralphy

### 1. Quick Start (fastest)

Just describe what you want:

```bash
ralphy start "Add dark mode toggle to settings page"
ralphy start "Implement rate limiting for API endpoints"
ralphy start "Add CSV export for user reports"
```

Ralphy creates everything: feature directory, PRD, specs, code, tests, and PR.

### 2. Custom PRD (more control)

For complex features, write your own PRD:

```bash
mkdir -p docs/features/my-feature
```

Create `docs/features/my-feature/PRD.md`:

```markdown
# User Authentication

## Context
Our app needs secure user authentication before launch.

## Objective
Implement OAuth2 login with Google and GitHub providers.

## Features
- Social login buttons on landing page
- User profile creation on first login
- Session management with secure cookies
- Logout functionality

## Constraints
- Use existing User model
- Must work with current session middleware
- No additional database migrations if possible
```

Then launch:

```bash
ralphy start my-feature
```

## The Workflow

```
PRD → [SPEC] → You approve → [DEV] → [QA] → You approve → [PR]
```

| Phase | What happens | You do |
|-------|--------------|--------|
| **SPEC** | Generates architecture + task list | Review SPEC.md and TASKS.md |
| **DEV** | Implements all tasks, writes tests | Watch progress |
| **QA** | Analyzes code quality and security | Review QA_REPORT.md |
| **PR** | Creates GitHub Pull Request | Merge when ready |

You validate twice: after specs (before coding starts) and after QA (before PR creation).

## Commands Reference

```bash
# Start or resume a feature
ralphy start my-feature
ralphy start "Feature description"    # Quick Start mode
ralphy start my-feature --fresh       # Restart from scratch
ralphy start my-feature --no-progress # Hide live display

# Check status
ralphy status my-feature              # Single feature
ralphy status --all                   # All features

# Control
ralphy abort my-feature               # Stop running workflow
ralphy reset my-feature               # Clear state and start over

# Customize prompts for your stack
ralphy init-prompts                   # Copy templates to .ralphy/prompts/
ralphy init-prompts --force           # Overwrite existing
```

## Automatic Resume

Interrupted? Just run the same command again:

```bash
ralphy start my-feature
```

Ralphy resumes from exactly where it stopped - even mid-task during implementation.

## Project Structure

After running Ralphy:

```
my-project/
├── docs/features/my-feature/
│   ├── PRD.md           # Your requirements (input)
│   ├── SPEC.md          # Generated architecture
│   ├── TASKS.md         # Task list with status
│   ├── QA_REPORT.md     # Quality/security analysis
│   └── .ralphy/
│       └── state.json   # Workflow progress
├── .ralphy/
│   ├── config.yaml      # Project config (optional)
│   └── prompts/         # Custom prompts (optional)
└── [your code]          # Generated implementation
```

## Configuration (Optional)

Create `.ralphy/config.yaml` for project-wide settings:

```yaml
project:
  name: my-project

stack:
  language: ruby              # python, typescript, go, rust...
  test_command: bundle exec rspec

models:
  specification: sonnet       # Fast for specs
  implementation: opus        # Most capable for coding
  qa: sonnet
  pr: haiku                   # Fast for simple PR creation

timeouts:
  specification: 1800         # 30 min
  implementation: 14400       # 4 hours
  qa: 1800                    # 30 min
  pr: 600                     # 10 min
```

## Agent Orchestration (Advanced)

For large projects, you can define specialized Claude Code agents in `.claude/agents/`. The dev-agent will automatically discover and delegate tasks to them.

Create `.claude/agents/backend.md`:

```markdown
---
name: backend
description: Implements Rails models, controllers, and API endpoints
---

You are a backend specialist...
```

The dev-agent will delegate backend tasks to this agent via Claude's Task tool.

## TDD Mode

Enable test-driven development in your config:

```yaml
stack:
  tdd_enabled: true
```

The dev-agent will follow RED-GREEN-REFACTOR: write failing tests first, implement minimal code to pass, then refactor.

**Note**: TDD instructions apply to the dev-agent directly. If you use agent orchestration, delegated agents won't automatically inherit TDD mode - add TDD instructions to your custom agent prompts in `.claude/agents/` if needed.

## Writing Good PRDs

1. **Be specific** - "Add login" is vague; "Add OAuth2 login with Google" is clear
2. **List constraints** - Existing code, performance requirements, dependencies
3. **One feature per PRD** - Keep scope manageable for one PR
4. **Include examples** - Show expected API responses, UI behavior, etc.

## Development Setup

```bash
git clone <repo>
cd Ralphy
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest  # Run tests
```

## License

MIT
