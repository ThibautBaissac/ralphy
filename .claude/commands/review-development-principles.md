---
description: Review codebase against development principles (KISS, SRP, DRY, YAGNI, etc.)
argument-hint: [file-or-directory]
---

# Development Principles Review

Review the code against our core development principles defined in @DEVELOPMENT_PRINCIPLES.md.

## Target
$ARGUMENTS

If no target is specified, review the main codebase structure and identify the most significant violations.

## Review Process

For each principle, analyze the code and report findings:

### 1. KISS (Keep It Simple, Stupid)
- Identify over-engineered solutions
- Flag unnecessary complexity, layers, or abstractions
- Look for clever code that's hard to understand

### 2. SRP (Single Responsibility Principle)
- Find "god" classes or functions doing too much
- Identify modules with multiple reasons to change
- Check for mixed concerns (e.g., I/O mixed with business logic)

### 3. DRY (Don't Repeat Yourself)
- Spot duplicated logic across files
- Identify copy-pasted code blocks
- Find repeated patterns that should be abstracted

### 4. YAGNI (You Aren't Gonna Need It)
- Flag speculative features or unused abstractions
- Identify over-configurable code with unused options
- Find "just in case" code paths

### 5. Modular Design
- Check for clear module boundaries
- Assess interface clarity between components
- Identify tightly coupled modules that should be separated

### 6. Single Source of Truth
- Find duplicated configuration or constants
- Identify data that's defined in multiple places
- Check for drift-prone patterns

### 7. Coupling, Cohesion & Encapsulation
- Identify high coupling between unrelated modules
- Find low cohesion (scattered related functionality)
- Check for Law of Demeter violations (long call chains)
- Look for exposed internal details that should be hidden

## Output Format

For each issue found:

| Principle | Severity | Location | Issue | Recommendation |
|-----------|----------|----------|-------|----------------|
| KISS/SRP/etc. | High/Medium/Low | file:line | Description | How to fix |

## Summary

After the detailed review, provide:
1. **Overall Assessment**: How well does the code follow our principles?
2. **Top 3 Priority Fixes**: Most impactful improvements to make
3. **Patterns to Adopt**: Good practices already in the codebase to replicate
