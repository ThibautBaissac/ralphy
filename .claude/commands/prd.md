---
description: Generate a Ralphy-compatible PRD from a feature description
argument-hint: [feature description]
allowed-tools: Read, Write, Glob, Bash(git status:*)
---

# PRD Generation Command

You are generating a **PRD.md** file for use with Ralphy, an AI-powered development automation tool. The PRD must be well-structured, scoped for a single mergeable PR, and written in English.

## User's Feature Request

$ARGUMENTS

## Your Task

1. **Analyze the project context** by reading available files:
   - README.md (if exists)
   - package.json, pyproject.toml, Gemfile, Cargo.toml, or similar dependency files
   - Existing project structure via `git status` or file listing

2. **Generate a PRD.md** at the project root with this exact structure:

```markdown
# [Feature Title]

## Context
[Background on the project and why this feature is needed. Reference existing patterns and architecture where relevant.]

## Objective
[Clear, concise statement of what the feature accomplishes. Should be achievable in a single PR.]

## Features
- **Feature 1**: [Description of specific functionality]
- **Feature 2**: [Description of specific functionality]
[Add more as needed, but keep scope manageable]

## Constraints
- [Tech stack constraints from the project]
- [Dependencies to respect]
- [Code conventions to follow]
- [Testing requirements]
- [Any other technical limitations]

## Usage Examples
[Concrete examples of how the feature will be used, including code snippets or CLI commands where appropriate]
```

3. **Write the PRD.md file** to the project root

4. **Confirm creation** by summarizing:
   - The feature title
   - Number of features defined
   - Key constraints identified

## Guidelines

- Keep the PRD **scoped for a single mergeable PR** - avoid overly ambitious scope
- Be **specific and actionable** - vague requirements lead to poor implementations
- Identify **real constraints** from the codebase, not generic ones
- Write in **clear, professional English**
- If the user's description is vague, make reasonable assumptions and document them

## Start Now

Read the project context files and generate the PRD based on the user's feature request.
