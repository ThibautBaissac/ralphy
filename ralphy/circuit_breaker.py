"""Circuit breaker to protect against infinite loops and blocked agents."""

import hashlib
import threading
import time
from collections import Counter, deque
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional

from ralphy.config import CircuitBreakerConfig
from ralphy.constants import (
    CB_PR_PHASE_INACTIVITY_TIMEOUT_SECONDS,
    CB_QA_PHASE_INACTIVITY_TIMEOUT_SECONDS,
    CB_TEST_COMMAND_INACTIVITY_TIMEOUT_SECONDS,
)
from ralphy.state import Phase


class TriggerType(str, Enum):
    """Types of circuit breaker triggers."""

    INACTIVITY = "inactivity"
    REPEATED_ERROR = "repeated_error"
    TASK_STAGNATION = "task_stagnation"
    OUTPUT_SIZE = "output_size"


class CircuitBreakerState(str, Enum):
    """States of the circuit breaker."""

    CLOSED = "closed"
    OPEN = "open"


@dataclass
class CircuitBreakerContext:
    """Execution context for the circuit breaker."""

    phase: Phase
    is_dev_agent: bool = False
    test_command: Optional[str] = None


@dataclass
class _TriggerResult:
    """Internal trigger result (to separate lock and callbacks)."""

    trigger_type: Optional[TriggerType] = None
    attempts: int = 0
    is_open: bool = False


class CircuitBreaker:
    """Circuit breaker to detect and prevent infinite loops.

    Monitors 4 types of triggers:
    - INACTIVITY: No output for X seconds
    - REPEATED_ERROR: Same error repeated X times
    - TASK_STAGNATION: No task completion for X seconds
    - OUTPUT_SIZE: Output exceeding X bytes

    The circuit breaker has 2 states:
    - CLOSED: Normal operation, counts warnings
    - OPEN: Circuit open, agent must be stopped
    """

    def __init__(
        self,
        config: CircuitBreakerConfig,
        context: CircuitBreakerContext,
        on_warning: Optional[Callable[[TriggerType, int], None]] = None,
        on_trip: Optional[Callable[[TriggerType], None]] = None,
    ):
        """Initialize the circuit breaker.

        Args:
            config: Circuit breaker configuration
            context: Execution context (phase, agent, etc.)
            on_warning: Callback called on warning (trigger, attempts)
            on_trip: Callback called on trip (trigger)
        """
        self._config = config
        self._context = context
        self._on_warning = on_warning
        self._on_trip = on_trip

        # Thread-safe internal state
        self._lock = threading.Lock()
        self._state = CircuitBreakerState.CLOSED
        self._attempts = 0
        self._last_trigger: Optional[TriggerType] = None

        # Trigger tracking
        self._last_output_time = time.monotonic()
        self._last_task_completion_time = time.monotonic()
        self._total_output_bytes = 0
        self._error_hashes: deque[str] = deque(maxlen=10)
        self._error_counts: Counter[str] = Counter()  # O(1) error counting
        self._recent_output: deque[str] = deque(maxlen=50)

    @property
    def is_open(self) -> bool:
        """Returns True if the circuit is open."""
        with self._lock:
            return self._state == CircuitBreakerState.OPEN

    @property
    def state(self) -> CircuitBreakerState:
        """Returns the current state of the circuit breaker."""
        with self._lock:
            return self._state

    @property
    def last_trigger(self) -> Optional[TriggerType]:
        """Returns the last trigger that was activated."""
        with self._lock:
            return self._last_trigger

    @property
    def attempts(self) -> int:
        """Returns the current number of attempts (warnings)."""
        with self._lock:
            return self._attempts

    def reset(self) -> None:
        """Resets the circuit breaker."""
        with self._lock:
            self._state = CircuitBreakerState.CLOSED
            self._attempts = 0
            self._last_trigger = None
            self._last_output_time = time.monotonic()
            self._last_task_completion_time = time.monotonic()
            self._total_output_bytes = 0
            self._error_hashes.clear()
            self._error_counts.clear()
            self._recent_output.clear()

    def record_output(self, line: str) -> Optional[TriggerType]:
        """Records an output line and checks for triggers.

        Args:
            line: Output line to record

        Returns:
            TriggerType if a trigger was activated and circuit opened, None otherwise
        """
        if not self._config.enabled:
            return None

        trigger_result: Optional[_TriggerResult] = None

        with self._lock:
            if self._state == CircuitBreakerState.OPEN:
                return None

            # Update timing
            self._last_output_time = time.monotonic()

            # Track output size
            self._total_output_bytes += len(line.encode("utf-8"))

            # Store recent output for test command detection
            self._recent_output.append(line)

            # Check for task completion
            if self._is_task_completion(line):
                self._last_task_completion_time = time.monotonic()

            # Check output size trigger
            if self._total_output_bytes > self._config.max_output_size:
                trigger_result = self._trigger_internal(TriggerType.OUTPUT_SIZE)
            else:
                # Check for repeated errors
                error_hash = self._extract_error_hash(line)
                if error_hash:
                    trigger_result = self._check_repeated_error_internal(error_hash)

        # Callbacks called OUTSIDE lock to avoid deadlocks
        return self._notify_trigger(trigger_result)

    def check_inactivity(self) -> Optional[TriggerType]:
        """Checks the inactivity trigger.

        Returns:
            TriggerType.INACTIVITY if timeout exceeded and circuit opened
        """
        if not self._config.enabled:
            return None

        trigger_result: Optional[_TriggerResult] = None

        with self._lock:
            if self._state == CircuitBreakerState.OPEN:
                return None

            timeout = self._get_effective_inactivity_timeout()
            elapsed = time.monotonic() - self._last_output_time

            if elapsed > timeout:
                trigger_result = self._trigger_internal(TriggerType.INACTIVITY)

        # Callbacks called OUTSIDE lock
        return self._notify_trigger(trigger_result)

    def check_task_stagnation(self) -> Optional[TriggerType]:
        """Checks the task stagnation trigger.

        Note: This trigger only applies to dev-agent according to spec.
        For other agents, this method always returns None.

        Returns:
            TriggerType.TASK_STAGNATION if timeout exceeded and circuit opened
        """
        if not self._config.enabled:
            return None

        # Task stagnation only applies to dev-agent (spec section 6.1)
        if not self._context.is_dev_agent:
            return None

        trigger_result: Optional[_TriggerResult] = None

        with self._lock:
            if self._state == CircuitBreakerState.OPEN:
                return None

            elapsed = time.monotonic() - self._last_task_completion_time

            if elapsed > self._config.task_stagnation_timeout:
                trigger_result = self._trigger_internal(TriggerType.TASK_STAGNATION)

        # Callbacks called OUTSIDE lock
        return self._notify_trigger(trigger_result)

    def _get_effective_inactivity_timeout(self) -> int:
        """Returns the effective inactivity timeout based on context.

        Special cases (by priority):
        - Test command detected in recent output: 300s (tests can be long)
        - PR phase: 120s (git operations are longer)
        - QA phase: 180s (code analysis takes time)
        """
        # Test command running - highest priority as tests can be long
        if self._context.test_command:
            recent_text = "".join(self._recent_output)
            if self._context.test_command in recent_text:
                return CB_TEST_COMMAND_INACTIVITY_TIMEOUT_SECONDS

        # PR phase - longer delay for git operations
        if self._context.phase == Phase.PR:
            return CB_PR_PHASE_INACTIVITY_TIMEOUT_SECONDS

        # QA phase - longer delay for code analysis
        if self._context.phase == Phase.QA:
            return CB_QA_PHASE_INACTIVITY_TIMEOUT_SECONDS

        return self._config.inactivity_timeout

    def _extract_error_hash(self, line: str) -> Optional[str]:
        """Extracts an error hash from a line if it's an error.

        Detects common error patterns:
        - "Error:" or "ERROR:"
        - "error:" (lowercase)
        - "Exception:" or "EXCEPTION:"
        - "Traceback"
        - "FAILED"
        """
        line_lower = line.lower()
        error_patterns = [
            "error:",
            "exception:",
            "traceback",
            "failed",
            "fatal:",
            "panic:",
        ]

        for pattern in error_patterns:
            if pattern in line_lower:
                # Hash first 200 characters to identify unique error
                error_content = line[:200].strip()
                return hashlib.md5(error_content.encode()).hexdigest()

        return None

    def _check_repeated_error_internal(self, error_hash: str) -> Optional[_TriggerResult]:
        """Checks if an error is repeated too often (called under lock).

        Args:
            error_hash: MD5 hash of the error

        Returns:
            _TriggerResult if threshold reached, None otherwise
        """
        # Decrement count for oldest error if deque is at capacity
        if len(self._error_hashes) == self._error_hashes.maxlen:
            oldest = self._error_hashes[0]
            self._error_counts[oldest] -= 1
            if self._error_counts[oldest] <= 0:
                del self._error_counts[oldest]

        # Add new error hash and increment its count
        self._error_hashes.append(error_hash)
        self._error_counts[error_hash] += 1

        # O(1) lookup instead of O(n) sum
        if self._error_counts[error_hash] >= self._config.max_repeated_errors:
            return self._trigger_internal(TriggerType.REPEATED_ERROR)

        return None

    def _is_task_completion(self, line: str) -> bool:
        """Detects if a line indicates task completion.

        Recognized patterns:
        - "completed" or "COMPLETED"
        - "done" or "DONE"
        - "finished" or "FINISHED"
        - "success" or "SUCCESS"
        - Checkmarks: "✓", "✔", "[x]", "[X]"
        """
        line_lower = line.lower()
        completion_patterns = [
            "completed",
            "done",
            "finished",
            "success",
            "passed",
        ]

        for pattern in completion_patterns:
            if pattern in line_lower:
                return True

        # Checkmarks
        checkmarks = ["✓", "✔", "[x]", "[X]"]
        for mark in checkmarks:
            if mark in line:
                return True

        return False

    def _trigger_internal(self, trigger_type: TriggerType) -> _TriggerResult:
        """Activates a trigger and returns the result (called under lock).

        This method only updates internal state.
        Callbacks are called by _notify_trigger() outside the lock.

        Args:
            trigger_type: Type of trigger activated

        Returns:
            _TriggerResult with information for callback notification
        """
        self._attempts += 1
        self._last_trigger = trigger_type

        if self._attempts >= self._config.max_attempts:
            # Trip - open the circuit
            self._state = CircuitBreakerState.OPEN
            return _TriggerResult(
                trigger_type=trigger_type,
                attempts=self._attempts,
                is_open=True,
            )
        else:
            # Warning only
            return _TriggerResult(
                trigger_type=trigger_type,
                attempts=self._attempts,
                is_open=False,
            )

    def _notify_trigger(self, result: Optional[_TriggerResult]) -> Optional[TriggerType]:
        """Notifies callbacks following a trigger (called outside lock).

        This method must be called OUTSIDE the lock to avoid deadlocks
        if callbacks try to access the circuit breaker.

        Args:
            result: Trigger result, or None if no trigger

        Returns:
            TriggerType if circuit is now OPEN, None otherwise
        """
        if result is None or result.trigger_type is None:
            return None

        if result.is_open:
            # Circuit open - call on_trip
            if self._on_trip:
                self._on_trip(result.trigger_type)
            return result.trigger_type
        else:
            # Warning only - call on_warning
            if self._on_warning:
                self._on_warning(result.trigger_type, result.attempts)
            return None
