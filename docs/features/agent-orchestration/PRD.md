# PRD: Agent Orchestration for Dev Prompt

## Overview

Enable Ralphy's dev_prompt to discover and delegate task groups to specialized Claude Code agents when available in the target project, producing higher-quality code through orchestration patterns.

## Problem Statement

Currently, Ralphy's dev_agent uses a single prompt template that implements all tasks directly. This works but produces medium-quality output. Projects that have invested in specialized Claude Code agents (e.g., TDD orchestrators, security reviewers) cannot leverage them through Ralphy's workflow.

## Goals

1. **Auto-discover** Claude Code agents in `.claude/agents/`
2. **Delegate intelligently** by letting Claude match task groups to agent descriptions
3. **Hybrid execution** - use agents where applicable, direct implementation otherwise
4. **Transparent logging** - show which tasks used agents vs direct implementation
5. **Zero configuration** - works automatically when agents exist

## Non-Goals (Out of Scope for v1)

- Generating or creating agents for the user
- Custom Ralphy-specific agent format (only Claude Code native)
- Caching agent discovery results across runs
- Configuration toggle to disable orchestration
- Discovery from `~/.claude/agents/` (personal agents)

## User Stories

### US1: Developer with TDD Orchestrator
As a developer with a `tdd-orchestrator` agent in my project, I want Ralphy to automatically use it for model/controller tasks so I get strict RED→GREEN→REFACTOR cycles.

### US2: Developer without Agents
As a developer without any custom agents, I want Ralphy to work exactly as before with no behavior change.

### US3: Developer with Partial Coverage
As a developer with agents for some task types, I want Ralphy to use agents where applicable and fall back to direct implementation for others.

## Technical Design

### Architecture

```
DevAgent.build_prompt()
    ├── _discover_agents()  → reads .claude/agents/*.md
    ├── _format_agents()    → extracts name + description from frontmatter
    └── render template with {{discovered_agents}} or fallback
```

### Agent Discovery

**Location**: `.claude/agents/` in the target project (project-level only)

**Process**:
1. Check if `.claude/agents/` directory exists
2. Read all `*.md` files
3. Parse YAML frontmatter to extract `name` and `description`
4. Format as minimal list for prompt injection

**Output format** (injected into `{{discovered_agents}}`):
```markdown
- **tdd-orchestrator**: Orchestrates the full TDD cycle. Use for model/controller implementation.
- **security-auditor**: Security code review specialist. Use for auth and data handling.
```

### Prompt Template Changes

**File rename**: `dev_agent.md` → `dev_prompt.md`

**Conditional structure**:
```markdown
# Dev Prompt
{{resume_instruction}}
You are an expert {{language}} developer...

{{#if discovered_agents}}
## Agent Orchestration

The project has specialized agents available. Delegate task groups to appropriate agents using the Task tool.

### Available Agents
{{discovered_agents}}

### Orchestration Rules
- Analyze TASKS.md and group related tasks (e.g., all model tasks, all controller tasks)
- Match task groups to agent descriptions
- Use Task tool to delegate: `Task(subagent_type="agent-name", prompt="...")`
- For tasks with no matching agent, implement directly
- Log which approach was used for each task group

{{else}}
## Direct Implementation
{{tdd_instructions}}
{{/if}}

## Tasks to Implement
{{tasks_content}}
```

### Behavior Matrix

| Scenario | `{{discovered_agents}}` | TDD Instructions | Behavior |
|----------|------------------------|------------------|----------|
| No `.claude/agents/` dir | Empty/None | Included | Direct implementation |
| Empty `.claude/agents/` | Empty/None | Included | Direct implementation + log |
| Agents exist | Formatted list | Excluded | Orchestration mode |
| Agents exist, no match | Formatted list | Excluded | Claude decides, may use direct |

### Code Changes

**`ralphy/agents/dev.py`**:
```python
class DevAgent(BaseAgent):
    def _discover_agents(self) -> list[dict]:
        """Discover Claude Code agents in target project."""
        agents_dir = self.project_path / ".claude" / "agents"
        if not agents_dir.exists():
            return []

        agents = []
        for agent_file in agents_dir.glob("*.md"):
            frontmatter = self._parse_frontmatter(agent_file)
            if frontmatter and "name" in frontmatter and "description" in frontmatter:
                agents.append({
                    "name": frontmatter["name"],
                    "description": frontmatter["description"]
                })
        return agents

    def _format_agents(self, agents: list[dict]) -> str:
        """Format agents for prompt injection."""
        if not agents:
            return ""
        lines = [f"- **{a['name']}**: {a['description']}" for a in agents]
        return "\n".join(lines)

    def build_prompt(self) -> str:
        agents = self._discover_agents()
        discovered_agents = self._format_agents(agents)

        if agents:
            logger.info(f"Discovered {len(agents)} agents: {[a['name'] for a in agents]}")
        else:
            logger.info("No agents found, using direct implementation")

        return self.template.render(
            discovered_agents=discovered_agents,
            # ... other placeholders
        )
```

**`ralphy/prompts/dev_prompt.md`**: New template with conditional orchestration section

### Logging

When agents are discovered:
```
INFO: Discovered 2 agents: ['tdd-orchestrator', 'security-auditor']
```

When no agents found:
```
INFO: No agents found, using direct implementation
```

## Edge Cases

### No Agents Directory
- Log message, continue with direct implementation
- No error, no warning - this is expected for most projects

### Agent File Without Valid Frontmatter
- Skip that file silently
- Only include agents with both `name` and `description`

### Agent Fails During Execution
- Trust Claude to handle recovery
- No special Ralphy-level retry logic for agent failures
- Circuit breaker still applies at the overall execution level

### Agent Description Doesn't Match Any Task
- Include agent in `{{discovered_agents}}` anyway
- Claude decides relevance based on actual task content
- Unused agents cause no harm

## Testing Strategy

### Unit Tests

1. **Agent discovery with mocked directory**
   - Empty directory returns empty list
   - Valid agents parsed correctly
   - Invalid frontmatter skipped

2. **Agent formatting**
   - Correct markdown format
   - Empty list returns empty string

3. **Prompt rendering**
   - `{{discovered_agents}}` populated when agents exist
   - TDD instructions excluded when agents exist
   - TDD instructions included when no agents

4. **Conditional template logic**
   - Orchestration section rendered with agents
   - Direct implementation section rendered without agents

### Integration Tests

1. **Full workflow with sample agent**
   - Create temp project with `.claude/agents/test-agent.md`
   - Run DevAgent.build_prompt()
   - Verify agent appears in rendered prompt

## Success Metrics

- Feature works transparently (no user configuration needed)
- Existing projects without agents see no behavior change
- Projects with agents get orchestration automatically
- All automated tests pass

## Dependencies

- Claude Code CLI with Task tool support
- Target projects must use Claude Code native agent format

## Rollout Plan

1. Implement agent discovery in DevAgent
2. Create new `dev_prompt.md` template
3. Add unit tests
4. Add integration test
5. Update documentation
6. Rename file (`dev_agent.md` → `dev_prompt.md`)

## Open Questions

None - all questions resolved during specification refinement.
