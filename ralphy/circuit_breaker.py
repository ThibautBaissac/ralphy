"""Circuit breaker pour protéger contre les boucles infinies et agents bloqués."""

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
    """Types de triggers du circuit breaker."""

    INACTIVITY = "inactivity"
    REPEATED_ERROR = "repeated_error"
    TASK_STAGNATION = "task_stagnation"
    OUTPUT_SIZE = "output_size"


class CircuitBreakerState(str, Enum):
    """États du circuit breaker."""

    CLOSED = "closed"
    OPEN = "open"


@dataclass
class CircuitBreakerContext:
    """Contexte d'exécution pour le circuit breaker."""

    phase: Phase
    is_dev_agent: bool = False
    test_command: Optional[str] = None


@dataclass
class _TriggerResult:
    """Résultat interne d'un trigger (pour séparer lock et callbacks)."""

    trigger_type: Optional[TriggerType] = None
    attempts: int = 0
    is_open: bool = False


class CircuitBreaker:
    """Circuit breaker pour détecter et prévenir les boucles infinies.

    Surveille 4 types de triggers:
    - INACTIVITY: Aucune sortie pendant X secondes
    - REPEATED_ERROR: Même erreur répétée X fois
    - TASK_STAGNATION: Pas de tâche complétée pendant X secondes
    - OUTPUT_SIZE: Sortie dépassant X bytes

    Le circuit breaker a 2 états:
    - CLOSED: Fonctionnement normal, comptabilise les warnings
    - OPEN: Circuit ouvert, l'agent doit être arrêté
    """

    def __init__(
        self,
        config: CircuitBreakerConfig,
        context: CircuitBreakerContext,
        on_warning: Optional[Callable[[TriggerType, int], None]] = None,
        on_trip: Optional[Callable[[TriggerType], None]] = None,
    ):
        """Initialise le circuit breaker.

        Args:
            config: Configuration du circuit breaker
            context: Contexte d'exécution (phase, agent, etc.)
            on_warning: Callback appelé lors d'un warning (trigger, attempts)
            on_trip: Callback appelé lors du trip (trigger)
        """
        self._config = config
        self._context = context
        self._on_warning = on_warning
        self._on_trip = on_trip

        # État interne thread-safe
        self._lock = threading.Lock()
        self._state = CircuitBreakerState.CLOSED
        self._attempts = 0
        self._last_trigger: Optional[TriggerType] = None

        # Tracking pour les triggers
        self._last_output_time = time.monotonic()
        self._last_task_completion_time = time.monotonic()
        self._total_output_bytes = 0
        self._error_hashes: deque[str] = deque(maxlen=10)
        self._error_counts: Counter[str] = Counter()  # O(1) error counting
        self._recent_output: deque[str] = deque(maxlen=50)

    @property
    def is_open(self) -> bool:
        """Retourne True si le circuit est ouvert."""
        with self._lock:
            return self._state == CircuitBreakerState.OPEN

    @property
    def state(self) -> CircuitBreakerState:
        """Retourne l'état actuel du circuit breaker."""
        with self._lock:
            return self._state

    @property
    def last_trigger(self) -> Optional[TriggerType]:
        """Retourne le dernier trigger qui a été activé."""
        with self._lock:
            return self._last_trigger

    @property
    def attempts(self) -> int:
        """Retourne le nombre de tentatives (warnings) actuelles."""
        with self._lock:
            return self._attempts

    def reset(self) -> None:
        """Réinitialise le circuit breaker."""
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
        """Enregistre une ligne de sortie et vérifie les triggers.

        Args:
            line: Ligne de sortie à enregistrer

        Returns:
            TriggerType si un trigger a été activé et le circuit ouvert, None sinon
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

        # Callbacks appelés EN DEHORS du lock pour éviter les deadlocks
        return self._notify_trigger(trigger_result)

    def check_inactivity(self) -> Optional[TriggerType]:
        """Vérifie le trigger d'inactivité.

        Returns:
            TriggerType.INACTIVITY si le timeout est dépassé et circuit ouvert
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

        # Callbacks appelés EN DEHORS du lock
        return self._notify_trigger(trigger_result)

    def check_task_stagnation(self) -> Optional[TriggerType]:
        """Vérifie le trigger de stagnation des tâches.

        Note: Ce trigger ne s'applique qu'au dev-agent selon la spécification.
        Pour les autres agents, cette méthode retourne toujours None.

        Returns:
            TriggerType.TASK_STAGNATION si le timeout est dépassé et circuit ouvert
        """
        if not self._config.enabled:
            return None

        # La stagnation des tâches ne concerne que le dev-agent (spec section 6.1)
        if not self._context.is_dev_agent:
            return None

        trigger_result: Optional[_TriggerResult] = None

        with self._lock:
            if self._state == CircuitBreakerState.OPEN:
                return None

            elapsed = time.monotonic() - self._last_task_completion_time

            if elapsed > self._config.task_stagnation_timeout:
                trigger_result = self._trigger_internal(TriggerType.TASK_STAGNATION)

        # Callbacks appelés EN DEHORS du lock
        return self._notify_trigger(trigger_result)

    def _get_effective_inactivity_timeout(self) -> int:
        """Retourne le timeout d'inactivité effectif selon le contexte.

        Cas spéciaux (par ordre de priorité):
        - Test command détecté dans output récent: 300s (tests peuvent être longs)
        - Phase PR: 120s (opérations git plus longues)
        - Phase QA: 180s (analyse de code prend du temps)
        """
        # Test command en cours - priorité maximale car tests peuvent être longs
        if self._context.test_command:
            recent_text = "".join(self._recent_output)
            if self._context.test_command in recent_text:
                return CB_TEST_COMMAND_INACTIVITY_TIMEOUT_SECONDS

        # Phase PR - délai plus long pour les opérations git
        if self._context.phase == Phase.PR:
            return CB_PR_PHASE_INACTIVITY_TIMEOUT_SECONDS

        # Phase QA - délai plus long pour l'analyse de code
        if self._context.phase == Phase.QA:
            return CB_QA_PHASE_INACTIVITY_TIMEOUT_SECONDS

        return self._config.inactivity_timeout

    def _extract_error_hash(self, line: str) -> Optional[str]:
        """Extrait un hash d'erreur d'une ligne si c'est une erreur.

        Détecte les patterns d'erreur communs:
        - "Error:" ou "ERROR:"
        - "error:" (minuscule)
        - "Exception:" ou "EXCEPTION:"
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
                # Hash les 200 premiers caractères pour identifier l'erreur unique
                error_content = line[:200].strip()
                return hashlib.md5(error_content.encode()).hexdigest()

        return None

    def _check_repeated_error_internal(self, error_hash: str) -> Optional[_TriggerResult]:
        """Vérifie si une erreur est répétée trop souvent (appelé sous lock).

        Args:
            error_hash: Hash MD5 de l'erreur

        Returns:
            _TriggerResult si le seuil est atteint, None sinon
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
        """Détecte si une ligne indique une complétion de tâche.

        Patterns reconnus:
        - "completed" ou "COMPLETED"
        - "done" ou "DONE"
        - "finished" ou "FINISHED"
        - "success" ou "SUCCESS"
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
        """Active un trigger et retourne le résultat (appelé sous lock).

        Cette méthode ne fait que mettre à jour l'état interne.
        Les callbacks sont appelés par _notify_trigger() en dehors du lock.

        Args:
            trigger_type: Type de trigger activé

        Returns:
            _TriggerResult avec les informations pour notifier les callbacks
        """
        self._attempts += 1
        self._last_trigger = trigger_type

        if self._attempts >= self._config.max_attempts:
            # Trip - ouvre le circuit
            self._state = CircuitBreakerState.OPEN
            return _TriggerResult(
                trigger_type=trigger_type,
                attempts=self._attempts,
                is_open=True,
            )
        else:
            # Warning seulement
            return _TriggerResult(
                trigger_type=trigger_type,
                attempts=self._attempts,
                is_open=False,
            )

    def _notify_trigger(self, result: Optional[_TriggerResult]) -> Optional[TriggerType]:
        """Notifie les callbacks suite à un trigger (appelé hors lock).

        Cette méthode doit être appelée EN DEHORS du lock pour éviter
        les deadlocks si les callbacks tentent d'accéder au circuit breaker.

        Args:
            result: Résultat du trigger, ou None si pas de trigger

        Returns:
            TriggerType si le circuit est maintenant OPEN, None sinon
        """
        if result is None or result.trigger_type is None:
            return None

        if result.is_open:
            # Circuit ouvert - appelle on_trip
            if self._on_trip:
                self._on_trip(result.trigger_type)
            return result.trigger_type
        else:
            # Warning seulement - appelle on_warning
            if self._on_warning:
                self._on_warning(result.trigger_type, result.attempts)
            return None
