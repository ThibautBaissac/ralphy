# Integrating Ralphy into an existing project

## 1. Prerequisites

Verify you have:

```bash
# Claude Code CLI installed and authenticated
claude --version

# Git configured
git --version

# GitHub CLI authenticated (for PR creation)
gh auth status
```

## 2. Installation

### Option A: Install with pipx (recommended for CLI)

`pipx` installs Python CLI tools in isolated environments:

```bash
# Install pipx if needed
brew install pipx
pipx ensurepath

# Install Ralphy from local repo
cd /path/to/Ralphy/
pipx install -e .

# Or from an absolute path
pipx install -e /path/to/Ralphy/
```

### Option B: Install with uv (fastest)

`uv` is an ultra-fast Python package manager:

```bash
# Install uv if needed
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install Ralphy
uv tool install -e /path/to/Ralphy/
```

### Option C: Development installation (for contributors)

Create a virtualenv to develop on Ralphy:

```bash
cd /path/to/Ralphy/

# Create and activate virtualenv
python3 -m venv .venv
source .venv/bin/activate

# Install in editable mode with dev dependencies
pip install -e ".[dev]"
```

### Verify installation

```bash
ralphy --version
```

### Uninstall

```bash
# If installed with pipx
pipx uninstall ralphwiggum

# If installed with uv
uv tool uninstall ralphwiggum
```

## 3. Two ways to use Ralphy

### Option 1: Quick Start (fastest)

Launch directly with a feature description:

```bash
cd /path/to/my-existing-project
ralphy start "Add a push notification system"
```

Ralphy will automatically:
1. Create a feature name: `add-a-push-notification-system`
2. Create `docs/features/<feature>/PRD.md` with a minimal PRD
3. Launch the complete workflow

### Option 2: Manual PRD (more control)

#### 3.1 Create the feature structure

```bash
cd /path/to/my-existing-project
mkdir -p docs/features/push-notifications
```

#### 3.2 Create the PRD.md

Create `docs/features/push-notifications/PRD.md`:

```markdown
# Push Notification System

## Context
Existing Rails 8 application. Users need to be notified
in real-time of important actions (orders, messages, etc.).

## Objective
Implement a push notification system via WebSockets.

## Features
- Notification service with ActionCable
- React component to display notifications
- REST API to mark as read
- Database persistence (notifications table)

## Constraints
- Use ActionCable (already configured)
- Respect existing design (Tailwind CSS)
- RSpec tests for backend
- Jest tests for frontend
- Don't impact existing performance
```

#### 3.3 Optional configuration

Create `.ralphy/config.yaml` at the project root:

```yaml
project:
  name: my-project

models:
  specification: sonnet     # or opus, haiku
  implementation: opus      # most powerful model for implementation
  qa: sonnet
  pr: haiku                 # fast model for PR creation

stack:
  language: ruby
  test_command: bundle exec rspec

timeouts:
  specification: 1800      # 30 min
  implementation: 14400    # 4h
  qa: 1800                 # 30 min
  pr: 600                  # 10 min

circuit_breaker:
  enabled: true
  inactivity_timeout: 60
  max_repeated_errors: 3
```

## 4. Launch the workflow

```bash
# With the feature name
ralphy start push-notifications

# Or with Quick Start
ralphy start "Add push notifications"
```

### Available options

```bash
# Force a complete restart (ignore existing progress)
ralphy start push-notifications --fresh

# Disable real-time display
ralphy start push-notifications --no-progress
```

## 5. Interactive workflow

```
[14:30:01] Phase: SPECIFICATION
[14:30:45] Agent: spec-agent completed
[14:30:45] === VALIDATION REQUIRED ===
[14:30:45] Generated files:
[14:30:45]   - docs/features/push-notifications/SPEC.md
[14:30:45]   - docs/features/push-notifications/TASKS.md (8 tasks)
[14:30:45]
[14:30:45] Approve? [y/n]: _     ← Review specs before continuing
```

**You validate twice**:

1. After spec generation (SPEC.md + TASKS.md)
2. After QA report (before PR creation)

### Real-time display

During execution, you see:
- **Progress**: task progress bar
- **Activity**: files read/written, tests launched
- **Tokens**: consumption and estimated cost in USD

## 6. Useful commands

```bash
# View feature status
ralphy status push-notifications

# View all features in progress
ralphy status --all

# Interrupt if needed
ralphy abort push-notifications

# Reset state (with confirmation)
ralphy reset push-notifications
```

## 7. Automatic resume

If the workflow is interrupted (crash, timeout, Ctrl+C), relaunch:

```bash
ralphy start push-notifications
```

Ralphy automatically resumes:
- **Phase**: skips SPECIFICATION if SPEC.md already exists
- **Task**: resumes from the last completed task

To force a complete restart:

```bash
ralphy start push-notifications --fresh
```

## 8. Generated structure

After execution, your project will have:

```
my-existing-project/
├── docs/features/
│   └── push-notifications/
│       ├── PRD.md              # Your input
│       ├── SPEC.md             # Generated specifications
│       ├── TASKS.md            # Task list
│       ├── QA_REPORT.md        # Quality report
│       └── .ralphy/
│           └── state.json      # Workflow state
├── .ralphy/
│   ├── config.yaml             # Global config (optional)
│   └── prompts/                # Custom prompts (optional)
├── src/                        # Generated/modified code
└── tests/                      # Generated tests
```

## 9. Customize prompts

To adapt agent behavior to your stack:

```bash
# Copy default templates
ralphy init-prompts

# Overwrite existing prompts
ralphy init-prompts --force
```

This creates `.ralphy/prompts/` with 4 files you can edit:
- `spec_agent.md` - Specification generation
- `dev_agent.md` - Implementation
- `qa_agent.md` - Quality analysis
- `pr_agent.md` - PR creation

## 10. Best practices

| Do | Don't |
|----|-------|
| Precise, detailed PRD | Vague PRD ("improve the code") |
| Limited scope (1 feature = 1 PR) | Too broad scope |
| Specify existing stack | Let it guess |
| Mention conventions | Ignore existing style |
| Review SPEC.md before validation | Validate blindly |

## 11. Concrete example: Google OAuth

```markdown
# PRD.md - Add OAuth authentication

## Context
Existing Rails 8 application with Devise for classic auth.
Need to add Google OAuth authentication.

## Objective
Allow users to sign in via their Google account.

## Features
- "Sign in with Google" button on login page
- Automatic account creation on first OAuth login
- Link existing account if email matches

## Constraints
- Use `omniauth-google-oauth2` gem
- Respect existing design (Tailwind CSS)
- RSpec tests for new controllers
- Don't break existing Devise auth

## Environment variables
- GOOGLE_CLIENT_ID
- GOOGLE_CLIENT_SECRET
```

Then:

```bash
# Option 1: Create manually
mkdir -p docs/features/oauth-google
# Copy the PRD above to docs/features/oauth-google/PRD.md
ralphy start oauth-google

# Option 2: Quick Start
ralphy start "Add Google OAuth authentication with omniauth"
```

## 12. Troubleshooting

### "externally-managed-environment" error

If you see this error with `pip3 install`, it's normal on macOS with Homebrew Python. **Use pipx or uv** (see Installation section above).

```bash
# Doesn't work (externally-managed-environment error)
pip3 install -e .

# Use pipx
pipx install -e /path/to/Ralphy/

# Or uv
uv tool install -e /path/to/Ralphy/
```

### Workflow is stuck

```bash
# Check status
ralphy status my-feature

# Force stop
ralphy abort my-feature

# Reset completely
ralphy reset my-feature
```

### Resume not working

Verify that files exist:
- `docs/features/<feature>/SPEC.md`
- `docs/features/<feature>/TASKS.md`

Check state in `docs/features/<feature>/.ralphy/state.json`.

### "PRD.md not found" error

Make sure the file exists at `docs/features/<feature>/PRD.md`.

Or use Quick Start which generates the PRD automatically:
```bash
ralphy start "Description of your feature"
```

### "Claude Code CLI not found" error

```bash
# Install Claude Code
npm install -g @anthropic-ai/claude-code

# Verify authentication
claude --version
```

### "gh not found" error

```bash
# macOS
brew install gh

# Then authenticate
gh auth login
```

## 13. Limitations

- **Windows**: Not supported (technical limitation with `select()`)
- **One active workflow per feature**: But you can have multiple features in parallel
- **Reasonable scope**: One PRD = one mergeable PR
