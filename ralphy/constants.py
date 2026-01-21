"""Centralized constants for Ralphy configuration.

This module contains all magic numbers and default values used throughout
the Ralphy codebase to improve maintainability and discoverability.
"""

import re

# =============================================================================
# FEATURE NAME VALIDATION
# =============================================================================

# Feature name validation pattern - must start with alphanumeric,
# contain only alphanumeric, hyphens, underscores
FEATURE_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")

# =============================================================================
# TIMEOUT DEFAULTS (seconds)
# =============================================================================

# Phase-specific timeouts
SPEC_TIMEOUT_SECONDS = 1800  # 30 min - Specification phase
IMPL_TIMEOUT_SECONDS = 14400  # 4h - Implementation phase
QA_TIMEOUT_SECONDS = 1800  # 30 min - QA phase
PR_TIMEOUT_SECONDS = 600  # 10 min - PR phase
AGENT_TIMEOUT_SECONDS = 300  # 5 min - Default agent timeout (fallback)

# Retry configuration
DEFAULT_RETRY_ATTEMPTS = 2  # Total attempts (1 = no retry)
DEFAULT_RETRY_DELAY_SECONDS = 5  # Delay between retries

# =============================================================================
# CIRCUIT BREAKER DEFAULTS
# =============================================================================

# Standard thresholds
CB_INACTIVITY_TIMEOUT_SECONDS = 60  # No output for this long triggers warning
CB_MAX_REPEATED_ERRORS = 3  # Same error this many times triggers warning
CB_TASK_STAGNATION_TIMEOUT_SECONDS = 600  # 10 min - No task completion (dev-agent)
CB_MAX_OUTPUT_SIZE_BYTES = 524288  # 500KB - Cumulative output size limit
CB_MAX_ATTEMPTS = 3  # Warnings before circuit trips (opens)

# Context-aware inactivity timeouts
CB_PR_PHASE_INACTIVITY_TIMEOUT_SECONDS = 120  # 2 min - Git operations are slow
CB_QA_PHASE_INACTIVITY_TIMEOUT_SECONDS = 180  # 3 min - QA analysis reads many files
CB_TEST_COMMAND_INACTIVITY_TIMEOUT_SECONDS = 300  # 5 min - Tests can be long

# =============================================================================
# FILE SIZE THRESHOLDS (bytes)
# =============================================================================

# Artifact validation - minimum sizes indicating substantive content
MIN_SPEC_FILE_SIZE_BYTES = 1000  # SPEC.md minimum
MIN_TASKS_FILE_SIZE_BYTES = 200  # TASKS.md minimum
MIN_QA_REPORT_FILE_SIZE_BYTES = 500  # QA_REPORT.md minimum

# =============================================================================
# PROMPT VALIDATION
# =============================================================================

MIN_PROMPT_SIZE_CHARS = 100  # Minimum characters for a valid custom prompt

# =============================================================================
# DISPLAY / UI
# =============================================================================

SPEC_PREVIEW_LINES = 20  # Lines to show in spec validation summary

# =============================================================================
# TOKEN TRACKING DEFAULTS
# =============================================================================

DEFAULT_CONTEXT_WINDOW = 200000  # Claude context window size
DEFAULT_MAX_OUTPUT_TOKENS = 64000  # Claude max output tokens
