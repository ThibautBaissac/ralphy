# Ralphy Codebase Fixes Implementation Plan

This document outlines the prioritized implementation plan for fixes identified during the comprehensive code review.

## Overview

| Priority | Category | Issues | Estimated Complexity | Status |
|----------|----------|--------|---------------------|--------|
| P0 | Critical | 4 | High | ✅ **COMPLETED** |
| P1 | High | 12 | Medium | Pending |
| P2 | Medium | 18 | Low-Medium | Pending |
| P3 | Low | 5 | Low | Pending |

---

## Phase 1: Critical Thread Safety & Resource Leaks

**Goal**: Eliminate race conditions and resource leaks that could cause data corruption or undefined behavior.

**Status**: ✅ **COMPLETED** (2026-01-21)

### 1.1 StateManager Race Condition ✅ COMPLETED
- **File**: `ralphy/state.py:154-196`
- **Issue**: Lazy `_state` property initialization is not thread-safe; `save()` method lacks lock protection
- **Fix**:
  ```python
  # Add lock around lazy initialization
  @property
  def state(self) -> WorkflowState:
      with self._lock:
          if self._state is None:
              self._state = self._load_or_create()
          return self._state

  # Add lock to save() method
  def save(self) -> None:
      with self._lock:
          # existing save logic
  ```
- **Tests to add**: Concurrent read/write tests using `threading`
- **Risk**: Low - additive change with no behavior modification
- **Implementation notes**:
  - Added `threading.Lock` to `StateManager.__init__`
  - Implemented double-checked locking in `state` property
  - `save()` serializes state dict under lock, uses unique temp files per thread (`os.getpid()` + `threading.get_ident()`)
  - Added `TestStateManagerThreadSafety` test class with 3 concurrent tests

### 1.2 ClaudeRunner Process Cleanup Race ✅ ALREADY IMPLEMENTED
- **File**: `ralphy/claude.py:465-475`
- **Issue**: `self._process` can be set to `None` while reader thread still references it
- **Fix**:
  ```python
  # Store local reference before cleanup
  def _cleanup(self):
      process = self._process
      if process is not None:
          # Use local reference for all operations
          if process.poll() is None:
              process.terminate()
          self._process = None
  ```
- **Tests to add**: Concurrent abort during active process
- **Risk**: Low - defensive copy pattern
- **Implementation notes**: Already implemented in `_read_output_with_abort_check()` at line 251-253 which captures local reference before operations

### 1.3 Stdout File Descriptor Leak ✅ COMPLETED
- **File**: `ralphy/claude.py:384-391`
- **Issue**: `stdout` file descriptor not explicitly closed in cleanup path
- **Fix**:
  ```python
  def _cleanup(self):
      if self._process and self._process.stdout:
          try:
              self._process.stdout.close()
          except Exception:
              pass
      # ... rest of cleanup
  ```
- **Tests to add**: Verify FD count before/after multiple runs
- **Risk**: Low - additive cleanup
- **Implementation notes**: Added explicit `stdout.close()` in the `finally` block at lines 478-483

### 1.4 O(n²) String Concatenation ✅ COMPLETED
- **File**: `ralphy/claude.py:276-283`
- **Issue**: Character-by-character string building with `+=` is O(n²)
- **Fix**:
  ```python
  from io import StringIO

  # Replace:
  # current_text += char
  # With:
  buffer = StringIO()
  buffer.write(char)
  # ... later
  current_text = buffer.getvalue()
  ```
- **Tests to add**: Performance test with large output (>100KB)
- **Risk**: Low - internal implementation change
- **Implementation notes**:
  - Replaced `buffer = ""` with `buffer = StringIO()`
  - Changed `buffer += chunk` to `buffer.write(chunk)`
  - Used `buffer.getvalue()` to read and `buffer.tell() > 0` to check for content
  - Added `TestClaudeRunnerPerformance` test class validating 100KB output in <1s

---

## Phase 2: Code Quality & DRY Violations

**Goal**: Reduce code duplication and improve maintainability.

### 2.1 Extract Placeholder Replacement to BaseAgent
- **Files**: `ralphy/agents/spec.py`, `dev.py`, `qa.py`, `pr.py`
- **Issue**: Each agent duplicates placeholder replacement logic
- **Fix**:
  ```python
  # In BaseAgent
  def _replace_placeholders(self, template: str, context: dict) -> str:
      for key, value in context.items():
          template = template.replace(f"{{{{{key}}}}}", str(value))
      return template
  ```
- **Tests to add**: Unit test for placeholder replacement edge cases
- **Risk**: Medium - refactor touching all agents

### 2.2 Consolidate Orchestrator Phase Methods
- **File**: `ralphy/orchestrator.py:398-590`
- **Issue**: `_run_spec_phase()`, `_run_impl_phase()`, etc. share 80% identical code
- **Fix**:
  ```python
  def _run_phase(self, phase: Phase, agent: BaseAgent,
                 validation_gate: bool = False) -> bool:
      # Unified phase execution logic
      pass
  ```
- **Tests to add**: Ensure all phase behaviors preserved
- **Risk**: Medium - significant refactor

### 2.3 Remove DevAgent Re-instantiation
- **File**: `ralphy/orchestrator.py:71-99`
- **Issue**: DevAgent instantiated 4+ times unnecessarily
- **Fix**: Create agents once in `__init__` or use lazy singleton pattern
- **Risk**: Low - optimization

---

## Phase 3: Security Hardening

**Goal**: Close potential attack vectors.

### 3.1 Feature Name Path Traversal Validation
- **Files**: `ralphy/state.py`, `ralphy/orchestrator.py`
- **Issue**: Feature names not validated for path traversal attempts
- **Fix**:
  ```python
  import re

  def validate_feature_name(name: str) -> bool:
      # Reject path traversal attempts
      if '..' in name or name.startswith('/'):
          raise ValueError(f"Invalid feature name: {name}")
      # Enforce allowed pattern
      if not re.match(r'^[a-zA-Z0-9][a-zA-Z0-9_-]*$', name):
          raise ValueError(f"Invalid feature name format: {name}")
      return True
  ```
- **Tests to add**: Test with malicious inputs (`../etc/passwd`, `/root`)
- **Risk**: Low - input validation

### 3.2 Symlink Protection Enhancement
- **File**: `ralphy/state.py`
- **Issue**: Incomplete symlink checking before file operations
- **Fix**: Add `os.path.realpath()` validation before all file writes
- **Risk**: Low - defensive check

---

## Phase 4: Performance Optimizations

**Goal**: Improve runtime efficiency.

### 4.1 Cache Prompt Templates
- **File**: `ralphy/agents/base.py:65-88`
- **Issue**: Prompt templates read from disk on every agent invocation
- **Fix**:
  ```python
  class BaseAgent:
      _prompt_cache: ClassVar[dict[str, str]] = {}

      def _load_prompt(self, name: str) -> str:
          if name not in self._prompt_cache:
              self._prompt_cache[name] = self._read_prompt_file(name)
          return self._prompt_cache[name]
  ```
- **Risk**: Low - caching optimization

### 4.2 Optimize Circuit Breaker Error Counting
- **File**: `ralphy/circuit_breaker.py:285-290`
- **Issue**: O(n) deque iteration for error hash counting
- **Fix**:
  ```python
  from collections import Counter

  # Replace deque iteration with Counter
  self._error_counts = Counter()

  def record_error(self, error_hash: str):
      self._error_counts[error_hash] += 1
      if self._error_counts[error_hash] >= self.threshold:
          self._trigger(TriggerType.REPEATED_ERROR)
  ```
- **Risk**: Low - data structure change

### 4.3 Compile Progress Regex Patterns
- **File**: `ralphy/progress.py:128-140`
- **Issue**: 15+ regex patterns compiled per output line
- **Fix**:
  ```python
  # At module/class level
  TASK_PATTERN = re.compile(r'TASK_(?:START|COMPLETE)')
  FILE_PATTERN = re.compile(r'(?:WRITING|READING)_FILE')
  # ... etc
  ```
- **Risk**: Low - initialization optimization

---

## Phase 5: Test Coverage Expansion

**Goal**: Achieve >80% coverage on critical modules.

### 5.1 Logger Tests
- **File**: `tests/test_logger.py` (new)
- **Coverage targets**:
  - Live mode toggle
  - Log level filtering
  - Output formatting
  - File handler rotation

### 5.2 Validation Tests
- **File**: `tests/test_validation.py` (new)
- **Coverage targets**:
  - User approval flow
  - Rejection handling
  - Timeout behavior
  - Input sanitization

### 5.3 Orchestrator Phase Tests
- **File**: `tests/test_orchestrator.py` (expand)
- **Coverage targets**:
  - Each phase transition
  - Resume from interruption
  - Validation gate blocking
  - Error recovery paths

### 5.4 Edge Case Tests
- **Files**: Various test files
- **Scenarios**:
  - Empty PRD handling
  - Malformed TASKS.md
  - Network timeout during PR creation
  - Disk full during state save

---

## Phase 6: Documentation & Maintainability

**Goal**: Improve code comprehension and onboarding.

### 6.1 Add Class-Level Docstrings
- **Files**: `orchestrator.py`, `claude.py`, `circuit_breaker.py`
- **Template**:
  ```python
  class Orchestrator:
      """
      Central workflow controller for Ralphy feature development.

      Manages the lifecycle of feature implementation through 4 phases:
      SPECIFICATION -> IMPLEMENTATION -> QA -> PR

      Attributes:
          state_manager: Persistent state handler
          config: Project configuration

      Thread Safety:
          Not thread-safe. Single instance per feature workflow.
      """
  ```

### 6.2 Standardize Language (English)
- **Files**: `ralphy/agents/dev.py`, various
- **Issue**: Mixed French/English in regex patterns and comments
- **Fix**: Replace French patterns with English equivalents
  ```python
  # Replace: r'Tâche\s+(\d+(?:\.\d+)?)'
  # With:    r'Task\s+(\d+(?:\.\d+)?)'
  ```

### 6.3 Update CLAUDE.md
- **File**: `CLAUDE.md`
- **Updates needed**:
  - Document thread safety guarantees
  - Add troubleshooting for common race conditions
  - Document new validation added in Phase 3

---

## Implementation Schedule

| Phase | Description | Dependencies | Validation | Status |
|-------|-------------|--------------|------------|--------|
| 1 | Critical fixes | None | All existing tests pass | ✅ **COMPLETED** |
| 2 | DRY refactoring | Phase 1 | No behavior changes | Pending |
| 3 | Security | Phase 1 | Security test suite | Pending |
| 4 | Performance | Phase 1, 2 | Benchmark comparison | Pending |
| 5 | Test coverage | Phase 1-4 | Coverage report >80% | Pending |
| 6 | Documentation | Phase 1-5 | Review by maintainer | Pending |

---

## Validation Checklist

Before merging each phase:

### Phase 1 (Completed 2026-01-21)
- [x] All existing tests pass (`pytest`) - 198 tests pass
- [x] New tests added for changes - `TestStateManagerThreadSafety`, `TestClaudeRunnerPerformance`
- [x] No regressions in `pytest --cov`
- [ ] Manual smoke test: `ralphy start test-feature`
- [ ] Code review approved

### Phases 2-6 (Pending)
- [ ] All existing tests pass (`pytest`)
- [ ] New tests added for changes
- [ ] No regressions in `pytest --cov`
- [ ] Manual smoke test: `ralphy start test-feature`
- [ ] Code review approved

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Refactoring breaks existing behavior | Comprehensive test suite before Phase 2 |
| Thread safety fixes introduce deadlocks | Use consistent lock ordering, timeout on locks |
| Performance fixes cause memory issues | Add memory profiling to CI |
| Security fixes break legitimate use cases | Whitelist approach, extensive edge case testing |

---

## Success Metrics

- Zero critical/high severity issues remaining
- Test coverage >80% on critical modules
- No race conditions detected in stress testing
- Documentation coverage for all public APIs
