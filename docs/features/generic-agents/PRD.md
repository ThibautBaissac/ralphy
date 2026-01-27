# PRD: Generic Agent System with Sub-Agent Orchestration

## Overview

Refactor Ralphy from using embedded Rails-specific prompts to a generic agent system where agents are stored in the host project's `.claude/agents/` folder. This enables framework-agnostic workflows and allows users to customize agents for their specific tech stack (Rails, Python, Node, etc.).

## Goals

1. **Framework Agnostic**: Remove all Rails-specific content from base agents
2. **User Customizable**: Agents live in host project and can be tailored
3. **Sub-Agent Orchestration**: Dev-agent can delegate to specialized sub-agents
4. **TDD-First**: Dev-agent uses TDD approach when task type allows

## Non-Goals

- Backward compatibility with `.ralphy/prompts/` (clean break)
- Automatic tech stack detection
- Sub-agent parallel execution (sequential only for v1)

## Architecture

### File Structure

**Ralphy Source:**
```
ralphy/
├── templates/
│   └── agents/
│       ├── spec-agent.md
│       ├── dev-agent.md
│       ├── qa-agent.md
│       └── pr-agent.md
├── agents/              # Python agent classes (unchanged)
│   ├── base.py
│   ├── spec.py
│   ├── dev.py
│   ├── qa.py
│   └── pr.py
└── prompts/             # DELETE (breaking change)
```

**Host Project (after `ralphy init-agents`):**
```
.claude/
└── agents/
    ├── spec-agent.md      # Base agents (required)
    ├── dev-agent.md
    ├── qa-agent.md
    ├── pr-agent.md
    └── (optional sub-agents)
        ├── backend-agent.md
        ├── frontend-agent.md
        └── test-agent.md
```

### Agent Loading Priority

1. **Primary**: Host project's `.claude/agents/{agent}.md`
2. **Fallback**: Ralphy's `templates/agents/{agent}.md`

This allows partial customization — users can override only the agents they need to customize.

## Sub-Agent System

### Frontmatter Specification

Each agent file uses YAML frontmatter for self-description:

```markdown
---
name: backend-agent
description: "Handles database migrations, models, and API endpoints. Use for tasks involving data layer, ORM, or server-side business logic."
triggers: [model, migration, controller, api, database, service, repository]
tools: [Bash, Read, Write, Edit, Grep, Glob]
---

# Backend Agent

System prompt content here...
```

**Required Fields:**
- `name`: Unique identifier (kebab-case)
- `description`: When to use this agent (used by Claude for routing decisions)

**Optional Fields:**
- `triggers`: Keywords that suggest this agent is relevant
- `tools`: Tools this agent should have access to (informational)

### Sub-Agent Discovery

The dev-agent discovers sub-agents by:
1. Scanning `.claude/agents/*.md` files
2. Parsing frontmatter from each file
3. Filtering out base agents (`spec-agent`, `dev-agent`, `qa-agent`, `pr-agent`)
4. Building a list of available sub-agents with their descriptions

### Routing Behavior

**When sub-agents exist:**
- Dev-agent receives `{{sub_agents}}` placeholder with all discovered sub-agents
- For each task, Claude decides which sub-agent(s) to delegate to based on:
  - Task description keywords
  - Sub-agent descriptions and triggers
- If multiple sub-agents match, Claude chooses the most appropriate
- Sub-agents are exposed as tools to the dev-agent

**When no sub-agents exist:**
- Dev-agent handles all tasks directly (current behavior, just generic)

**When sub-agent fails:**
- Dev-agent takes over and completes the task itself
- Failure is logged but doesn't block the workflow

### Invalid Frontmatter Handling

- Files with missing/invalid frontmatter are skipped with a warning
- Workflow continues with remaining valid agents
- Warning includes filename and reason for skip

## TDD Behavior

### Heuristics

Dev-agent decides TDD approach based on task type:

**TDD-Friendly (write tests first):**
- model, service, utility, helper, validation
- business logic, calculation, transformation
- API endpoint, controller action

**Not TDD (implement first):**
- migration, schema change
- view, template, UI component
- config, documentation, styling
- infrastructure, deployment

### Override Mechanism

Users can override TDD behavior per-task in TASKS.md:

```markdown
## Task 3: [Create UserService]
- **Status**: pending
- **TDD**: true  # Force TDD approach
- **Description**: ...
```

```markdown
## Task 7: [Add loading spinner to dashboard]
- **Status**: pending
- **TDD**: false  # Skip TDD for UI task
- **Description**: ...
```

## CLI Changes

### New Command: `ralphy init-agents`

**Replaces**: `ralphy init-prompts`

**Usage:**
```bash
# Initialize agents in current directory
ralphy init-agents

# Initialize agents in specific project
ralphy init-agents /path/to/project

# Force overwrite existing agents
ralphy init-agents --force
```

**Behavior:**
1. Creates `.claude/agents/` directory if not exists
2. Copies 4 base agents from `ralphy/templates/agents/`
3. Skips existing files (unless `--force`)
4. Prints customization instructions

**Output Example:**
```
Created .claude/agents/
  - spec-agent.md
  - dev-agent.md
  - qa-agent.md
  - pr-agent.md

Customize these agents for your tech stack!
Add sub-agents to .claude/agents/ for specialized tasks.
See: https://github.com/ThibautBaissac/Ralphy#custom-agents
```

### Removed Command

- `ralphy init-prompts` — removed (breaking change)

## Placeholder System

### Available Placeholders

| Placeholder | Description | Agents |
|-------------|-------------|--------|
| `{{project_name}}` | Project name from config | All |
| `{{language}}` | Tech stack from config | All |
| `{{test_command}}` | Test command from config | spec, dev |
| `{{feature_path}}` | Path to feature directory | All |
| `{{prd_content}}` | PRD.md content | spec |
| `{{spec_content}}` | SPEC.md content | dev, qa, pr |
| `{{tasks_content}}` | TASKS.md content | dev |
| `{{sub_agents}}` | List of sub-agents with descriptions | dev |
| `{{resume_instruction}}` | Resume instructions for interrupted workflow | dev |
| `{{branch_name}}` | Git branch name | pr |
| `{{qa_report}}` | QA report content | pr |
| `{{tdd_instruction}}` | TDD guidance based on task type | dev |

### Sub-Agents Placeholder Format

The `{{sub_agents}}` placeholder expands to:

```markdown
## Available Sub-Agents

You can delegate tasks to these specialized agents:

### backend-agent
**Description**: Handles database migrations, models, and API endpoints.
**Triggers**: model, migration, controller, api, database, service

### frontend-agent
**Description**: Handles UI components, views, and client-side logic.
**Triggers**: view, component, template, styling, javascript

### test-agent
**Description**: Writes and maintains test suites.
**Triggers**: test, spec, fixture, mock
```

## Generic Agent Templates

### Spec-Agent (spec-agent.md)

Core responsibilities:
- Analyze PRD and extract requirements
- Design technical architecture (framework-agnostic)
- Generate SPEC.md with architecture decisions
- Generate TASKS.md with ordered, atomic tasks
- Include test requirements per task

### Dev-Agent (dev-agent.md)

Core responsibilities:
- Orchestrate sub-agents when available
- Process tasks from TASKS.md sequentially
- Apply TDD when task type allows
- Update task status (pending → in_progress → completed)
- Fall back to direct implementation when no sub-agents match
- Take over if sub-agent fails

### QA-Agent (qa-agent.md)

Core responsibilities:
- Analyze implemented code for quality
- Check for OWASP Top 10 vulnerabilities (generic, not Rails-specific)
- Verify test coverage
- Generate QA_REPORT.md with findings

### PR-Agent (pr-agent.md)

Core responsibilities:
- Create feature branch
- Commit changes with conventional commit messages
- Push to remote
- Create Pull Request via `gh` CLI
- Include QA summary in PR description

## Migration Path

### For Existing Ralphy Users

1. Run `ralphy init-agents` in your project
2. Customize agents for your tech stack
3. Delete `.ralphy/prompts/` if exists (no longer used)
4. Update any custom prompts to new frontmatter format

### Breaking Changes

- `ralphy init-prompts` command removed
- `.ralphy/prompts/` no longer read (use `.claude/agents/`)
- Prompt placeholders unchanged but content is generic

## Success Criteria

1. `ralphy init-agents` creates all 4 base agents
2. Agents load from `.claude/agents/` with fallback to templates
3. Sub-agent discovery parses frontmatter correctly
4. Invalid frontmatter files are skipped with warning
5. Dev-agent delegates to sub-agents when available
6. Dev-agent handles tasks directly when no sub-agents exist
7. Dev-agent takes over when sub-agent fails
8. TDD heuristics apply correctly based on task type
9. TDD override in TASKS.md is respected
10. All existing Ralphy workflows complete successfully with generic agents

## Security Considerations

- `tools` field in frontmatter is informational only
- Actual tool permissions controlled by Claude Code's permission system
- No execution of arbitrary code from frontmatter
- Sub-agent prompts are user-controlled (trust model same as current prompts)

## Future Considerations (Out of Scope)

- Parallel sub-agent execution
- Sub-agent communication/handoff
- Automatic tech stack detection from project files
- Agent marketplace/sharing
- Visual agent editor
