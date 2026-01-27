# Implementation Checklist: Generic Agent System

Quick reference for implementing the generic agent system.

## Phase 1: File Structure & Templates

- [ ] Create `ralphy/templates/agents/` directory
- [ ] Create generic `spec-agent.md` template
- [ ] Create generic `dev-agent.md` template (with orchestration section)
- [ ] Create generic `qa-agent.md` template
- [ ] Create generic `pr-agent.md` template
- [ ] Delete `ralphy/prompts/` directory
- [ ] Update `.gitignore` if needed

## Phase 2: Agent Loading

- [ ] Create `ralphy/agent_loader.py` (or add to existing module)
- [ ] Implement `load_agent(agent_name)` with fallback logic:
  1. Check `.claude/agents/{agent_name}.md`
  2. Fall back to `ralphy/templates/agents/{agent_name}.md`
- [ ] Update `BaseAgent` to use new loading mechanism
- [ ] Add tests for agent loading priority

## Phase 3: Frontmatter Parsing

- [ ] Add `pyyaml` or use existing YAML dependency
- [ ] Create `parse_frontmatter(content) -> dict` function
- [ ] Handle missing/invalid frontmatter gracefully
- [ ] Return `None` with warning for invalid files
- [ ] Add tests for frontmatter parsing edge cases

## Phase 4: Sub-Agent Discovery

- [ ] Create `discover_sub_agents(project_path) -> list[SubAgent]`
- [ ] Scan `.claude/agents/*.md` files
- [ ] Filter out base agents by name
- [ ] Parse frontmatter from each file
- [ ] Skip invalid files with warning
- [ ] Build `SubAgent` dataclass with: name, description, triggers, tools
- [ ] Add tests for discovery logic

## Phase 5: Dev-Agent Orchestration

- [ ] Add `{{sub_agents}}` placeholder support
- [ ] Format sub-agents list as markdown for prompt injection
- [ ] Update dev-agent template with orchestration instructions:
  - When to delegate vs handle directly
  - How to call sub-agents
  - Failure handling (take over)
- [ ] Add `{{tdd_instruction}}` placeholder
- [ ] Implement TDD heuristics function
- [ ] Support `TDD: true/false` override in TASKS.md parsing
- [ ] Add tests for orchestration behavior

## Phase 6: CLI Changes

- [ ] Create `ralphy init-agents` command
- [ ] Implement directory creation
- [ ] Implement template copying with skip logic
- [ ] Add `--force` flag for overwrite
- [ ] Print customization instructions on success
- [ ] Remove `ralphy init-prompts` command
- [ ] Update CLI help text
- [ ] Add tests for init-agents command

## Phase 7: Update Existing Agents

- [ ] Update `SpecAgent` to use new loader
- [ ] Update `DevAgent` to use new loader + sub-agent discovery
- [ ] Update `QAAgent` to use new loader
- [ ] Update `PRAgent` to use new loader
- [ ] Remove Rails-specific code from agent classes

## Phase 8: Documentation

- [ ] Update README.md with new agent system
- [ ] Update CLAUDE.md with new architecture
- [ ] Add sub-agent creation guide
- [ ] Document frontmatter specification
- [ ] Add examples for common tech stacks (Rails, Python, Node)

## Phase 9: Testing

- [ ] Test: init-agents creates all 4 base agents
- [ ] Test: agent loading from .claude/agents/ works
- [ ] Test: fallback to templates works
- [ ] Test: sub-agent discovery with valid frontmatter
- [ ] Test: sub-agent discovery skips invalid frontmatter
- [ ] Test: dev-agent receives sub-agents in prompt
- [ ] Test: dev-agent works without sub-agents
- [ ] Test: TDD heuristics categorize tasks correctly
- [ ] Test: TDD override in TASKS.md is respected
- [ ] Integration test: full workflow with generic agents

---

## Key Decisions Reference

| Decision | Choice |
|----------|--------|
| Agent templates location | `ralphy/templates/agents/` |
| Runtime loading | Host `.claude/agents/` → fallback to templates |
| Sub-agent discovery | Self-describing YAML frontmatter |
| No sub-agents | Dev-agent handles everything |
| Sub-agent fails | Dev-agent takes over |
| Multi-match routing | Let Claude decide |
| Invalid frontmatter | Skip with warning |
| TDD behavior | Heuristics + per-task override |
| Init command | `ralphy init-agents` (replaces init-prompts) |
| Backward compat | Clean break |

---

## Frontmatter Template

```yaml
---
name: my-agent
description: "Clear description of when to use this agent."
triggers: [keyword1, keyword2, keyword3]
tools: [Bash, Read, Write, Edit, Grep, Glob]
---
```

---

## TDD Heuristics Quick Reference

**TDD-Friendly:**
- model, service, utility, helper, validation
- business logic, calculation, transformation
- API endpoint, controller action

**Not TDD:**
- migration, schema, view, template, UI
- config, documentation, styling
- infrastructure, deployment
