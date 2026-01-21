---
description: Personalize Ralphy prompt templates for your tech stack and preferences
argument-hint: [description of your stack, language, conventions]
allowed-tools: Read, Write, Glob
---

# Personalize Prompts Command

You are personalizing Ralphy's prompt templates based on user preferences. This allows adapting the prompts to different tech stacks, output languages, and conventions.

## User Request

$ARGUMENTS

## Your Task

### Step 1: Check Prerequisites

First, verify that `.ralphy/prompts/` directory exists by checking for any of these files:
- `.ralphy/prompts/spec_agent.md`
- `.ralphy/prompts/dev_agent.md`
- `.ralphy/prompts/qa_agent.md`
- `.ralphy/prompts/pr_agent.md`

**If the directory or files don't exist:**
Stop immediately and tell the user:
> "Custom prompts not found. Please run `ralphy init-prompts .` first to create custom prompt templates that can be personalized."

**If files exist:** Continue to Step 2.

### Step 2: Read Current Prompts

Read all 4 prompt templates from `.ralphy/prompts/`:
1. `spec_agent.md` - Specification generation agent
2. `dev_agent.md` - Implementation/development agent
3. `qa_agent.md` - Quality assurance agent
4. `pr_agent.md` - Pull request creation agent

### Step 3: Analyze User Request

Extract from the user's description:
- **Tech stack**: Framework (Rails, Next.js, Django, etc.), language (TypeScript, Python, Ruby, etc.)
- **Output language**: What language to write the prompts in (English, French, Spanish, etc.)
- **Testing tools**: Jest, RSpec, pytest, etc.
- **Conventions**: Coding style, patterns, specific libraries mentioned

### Step 4: Transform Each Prompt

For each prompt file, adapt:
- Framework-specific examples and conventions
- Testing tool references and commands
- Library and pattern recommendations
- Language/translation of the prompt text (if requested)

### Step 5: CRITICAL - Elements You MUST Preserve

**NEVER remove or modify these elements:**

1. **EXIT_SIGNAL instruction** - Every prompt MUST contain instructions for the agent to emit `EXIT_SIGNAL: true` when complete. This is REQUIRED for Ralphy to detect agent completion.

2. **All placeholders** - Keep these exactly as-is (including the double curly braces):
   - `{{project_name}}`
   - `{{language}}`
   - `{{test_command}}`
   - `{{feature_path}}`
   - `{{prd_content}}`
   - `{{spec_content}}`
   - `{{tasks_content}}`
   - `{{resume_instruction}}`
   - `{{branch_name}}`
   - `{{qa_report}}`

3. **Task status workflow** - The dev_agent prompt MUST preserve the task status system:
   - `pending` → `in_progress` → `completed`
   - Task status markers in TASKS.md

4. **File structure requirements**:
   - SPEC.md format and sections
   - TASKS.md format with numbered tasks and status markers
   - QA_REPORT.md structure

5. **Minimum prompt length** - Each prompt must be at least 100 characters (validation requirement)

### Step 6: Write Updated Prompts

Write the transformed prompts back to `.ralphy/prompts/`:
- `.ralphy/prompts/spec_agent.md`
- `.ralphy/prompts/dev_agent.md`
- `.ralphy/prompts/qa_agent.md`
- `.ralphy/prompts/pr_agent.md`

### Step 7: Confirm Changes

Provide a summary of what was updated:
- List each file modified
- Describe the key changes (tech stack, language, testing tools)
- Confirm that EXIT_SIGNAL and placeholders were preserved

## Example Transformations

**User request**: "TypeScript Next.js with Jest, in English"

Changes to make:
- Replace Ruby/Rails examples with TypeScript/Next.js
- Replace RSpec with Jest
- Replace FactoryBot with testing-library or similar
- Translate French text to English
- Update framework-specific patterns (Hotwire → React, Pundit → middleware, etc.)

**User request**: "Python Django with pytest, keep in French"

Changes to make:
- Replace Ruby/Rails examples with Python/Django
- Replace RSpec with pytest
- Update ORM examples (ActiveRecord → Django ORM)
- Keep text in French
- Update conventions for Python (PEP 8, etc.)

## Start Now

Check for the `.ralphy/prompts/` directory and begin personalizing the prompts based on the user's request.
