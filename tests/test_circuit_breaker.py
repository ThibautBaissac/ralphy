"""Tests pour le module circuit_breaker."""

import threading
import time

import pytest

from ralphy.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerContext,
    CircuitBreakerState,
    TriggerType,
)
from ralphy.config import CircuitBreakerConfig
from ralphy.state import Phase


class TestCircuitBreakerConfig:
    """Tests pour CircuitBreakerConfig."""

    def test_default_values(self):
        """Test des valeurs par défaut."""
        config = CircuitBreakerConfig()
        assert config.enabled is True
        assert config.inactivity_timeout == 60
        assert config.max_repeated_errors == 3
        assert config.task_stagnation_timeout == 600
        assert config.max_output_size == 524288
        assert config.max_attempts == 3

    def test_custom_values(self):
        """Test avec des valeurs personnalisées."""
        config = CircuitBreakerConfig(
            enabled=False,
            inactivity_timeout=30,
            max_repeated_errors=5,
            task_stagnation_timeout=300,
            max_output_size=1024,
            max_attempts=2,
        )
        assert config.enabled is False
        assert config.inactivity_timeout == 30
        assert config.max_repeated_errors == 5
        assert config.task_stagnation_timeout == 300
        assert config.max_output_size == 1024
        assert config.max_attempts == 2


class TestCircuitBreakerContext:
    """Tests pour CircuitBreakerContext."""

    def test_default_values(self):
        """Test des valeurs par défaut."""
        context = CircuitBreakerContext(phase=Phase.IMPLEMENTATION)
        assert context.phase == Phase.IMPLEMENTATION
        assert context.is_dev_agent is False
        assert context.test_command is None

    def test_custom_values(self):
        """Test avec des valeurs personnalisées."""
        context = CircuitBreakerContext(
            phase=Phase.QA,
            is_dev_agent=True,
            test_command="npm test",
        )
        assert context.phase == Phase.QA
        assert context.is_dev_agent is True
        assert context.test_command == "npm test"


class TestCircuitBreaker:
    """Tests pour la classe CircuitBreaker."""

    @pytest.fixture
    def default_config(self):
        """Configuration par défaut pour les tests."""
        return CircuitBreakerConfig(
            enabled=True,
            inactivity_timeout=1,  # 1s pour tests rapides
            max_repeated_errors=3,
            task_stagnation_timeout=2,  # 2s pour tests rapides
            max_output_size=100000,  # Large pour éviter trigger accidentel
            max_attempts=3,
        )

    @pytest.fixture
    def default_context(self):
        """Contexte par défaut pour les tests."""
        return CircuitBreakerContext(phase=Phase.IMPLEMENTATION)

    @pytest.fixture
    def circuit_breaker(self, default_config, default_context):
        """Circuit breaker pour les tests."""
        return CircuitBreaker(
            config=default_config,
            context=default_context,
        )

    def test_initial_state_closed(self, circuit_breaker):
        """Test que l'état initial est CLOSED."""
        assert circuit_breaker.state == CircuitBreakerState.CLOSED
        assert circuit_breaker.is_open is False
        assert circuit_breaker.last_trigger is None
        assert circuit_breaker.attempts == 0

    def test_record_output_updates_timing(self, circuit_breaker):
        """Test que record_output met à jour le timing."""
        # Pas de trigger pour une sortie normale
        result = circuit_breaker.record_output("normal output line\n")
        assert result is None
        assert circuit_breaker.is_open is False

    def test_output_size_trigger(self, default_context):
        """Test du trigger output_size."""
        warnings = []
        trips = []

        # Config spécifique avec petite limite de taille
        config = CircuitBreakerConfig(
            enabled=True,
            inactivity_timeout=60,
            max_repeated_errors=10,
            task_stagnation_timeout=600,
            max_output_size=100,  # 100 bytes
            max_attempts=3,
        )

        cb = CircuitBreaker(
            config=config,
            context=default_context,
            on_warning=lambda t, a: warnings.append((t, a)),
            on_trip=lambda t: trips.append(t),
        )

        # Première ligne: 51 bytes, total = 51
        result = cb.record_output("x" * 50 + "\n")
        assert result is None

        # Deuxième ligne: 51 bytes, total = 102 > 100 -> warning 1
        result = cb.record_output("x" * 50 + "\n")
        assert result is None
        assert len(warnings) == 1

        # Troisième ligne: trigger à nouveau -> warning 2
        result = cb.record_output("x" * 50 + "\n")
        assert result is None
        assert len(warnings) == 2

        # Quatrième ligne: trigger -> trip (3ème tentative)
        result = cb.record_output("x" * 50 + "\n")
        assert result == TriggerType.OUTPUT_SIZE

        assert cb.is_open is True
        assert cb.last_trigger == TriggerType.OUTPUT_SIZE
        assert len(trips) == 1

    def test_repeated_error_detection(self, default_context):
        """Test de la détection d'erreurs répétées."""
        warnings = []
        trips = []

        # Config avec repeated errors = 3 et max_attempts = 3
        config = CircuitBreakerConfig(
            enabled=True,
            inactivity_timeout=60,
            max_repeated_errors=3,
            task_stagnation_timeout=600,
            max_output_size=100000,
            max_attempts=3,
        )

        cb = CircuitBreaker(
            config=config,
            context=default_context,
            on_warning=lambda t, a: warnings.append((t, a)),
            on_trip=lambda t: trips.append(t),
        )

        # Même erreur répétée - après 3 occurrences, trigger warning
        same_error = "Error: Something went wrong\n"

        # 1ère et 2ème occurrence - pas encore de trigger
        cb.record_output(same_error)
        cb.record_output(same_error)
        assert len(warnings) == 0

        # 3ème occurrence - premier trigger (warning 1)
        cb.record_output(same_error)
        assert len(warnings) == 1

        # 4ème occurrence - deuxième trigger (warning 2)
        cb.record_output(same_error)
        assert len(warnings) == 2

        # 5ème occurrence - trip (3ème tentative)
        result = cb.record_output(same_error)
        assert result == TriggerType.REPEATED_ERROR
        assert cb.is_open is True
        assert len(trips) == 1

    def test_inactivity_trigger(self, default_config, default_context):
        """Test du trigger d'inactivité."""
        cb = CircuitBreaker(
            config=default_config,
            context=default_context,
        )

        # Record initial output
        cb.record_output("initial\n")

        # Attend le timeout
        time.sleep(default_config.inactivity_timeout + 0.2)

        # Vérifie l'inactivité multiple fois pour atteindre max_attempts
        for i in range(default_config.max_attempts):
            result = cb.check_inactivity()
            # Reset le timer interne pour simuler une nouvelle tentative
            if result is None:
                # Force le timeout à nouveau
                time.sleep(default_config.inactivity_timeout + 0.1)

        assert cb.last_trigger == TriggerType.INACTIVITY

    def test_task_stagnation_trigger(self, default_config):
        """Test du trigger de stagnation des tâches (dev-agent uniquement)."""
        # Le trigger de stagnation ne s'applique qu'au dev-agent
        dev_context = CircuitBreakerContext(
            phase=Phase.IMPLEMENTATION,
            is_dev_agent=True,  # Important: doit être True pour ce trigger
        )
        cb = CircuitBreaker(
            config=default_config,
            context=dev_context,
        )

        # Attend le timeout de stagnation
        time.sleep(default_config.task_stagnation_timeout + 0.2)

        # Vérifie la stagnation multiple fois
        for i in range(default_config.max_attempts):
            result = cb.check_task_stagnation()
            if result is None:
                time.sleep(default_config.task_stagnation_timeout + 0.1)

        assert cb.last_trigger == TriggerType.TASK_STAGNATION

    def test_task_stagnation_ignored_for_non_dev_agent(self, default_config, default_context):
        """Test que la stagnation est ignorée pour les agents non-dev."""
        # Le contexte par défaut a is_dev_agent=False
        cb = CircuitBreaker(
            config=default_config,
            context=default_context,
        )

        # Attend le timeout de stagnation
        time.sleep(default_config.task_stagnation_timeout + 0.2)

        # Vérifie que le trigger ne se déclenche pas
        result = cb.check_task_stagnation()
        assert result is None
        assert cb.last_trigger is None  # Pas de trigger pour non-dev-agent

    def test_task_completion_resets_stagnation(self, default_config, default_context):
        """Test que la complétion de tâche reset le timer de stagnation."""
        cb = CircuitBreaker(
            config=default_config,
            context=default_context,
        )

        # Attend presque le timeout
        time.sleep(default_config.task_stagnation_timeout - 0.5)

        # Signal de complétion
        cb.record_output("Task completed successfully\n")

        # Vérifie qu'il n'y a pas de trigger
        result = cb.check_task_stagnation()
        assert result is None

    def test_warning_before_open(self, default_context):
        """Test que des warnings sont émis avant l'ouverture."""
        warnings = []
        trips = []

        # Config avec petite limite pour triggering rapide
        config = CircuitBreakerConfig(
            enabled=True,
            inactivity_timeout=60,
            max_repeated_errors=10,
            task_stagnation_timeout=600,
            max_output_size=50,  # Très petit pour trigger immédiat
            max_attempts=3,
        )

        cb = CircuitBreaker(
            config=config,
            context=default_context,
            on_warning=lambda t, a: warnings.append((t, a)),
            on_trip=lambda t: trips.append(t),
        )

        # Génère des triggers progressifs via output_size
        # Première ligne: 51 bytes > 50, trigger warning 1
        cb.record_output("x" * 50 + "\n")
        assert len(warnings) == 1

        # Deuxième ligne: trigger warning 2
        cb.record_output("x" * 50 + "\n")
        assert len(warnings) == 2

        # Troisième ligne: trip
        cb.record_output("x" * 50 + "\n")

        # Devrait avoir max_attempts - 1 warnings et 1 trip
        assert len(warnings) == config.max_attempts - 1
        assert len(trips) == 1

    def test_reset(self, circuit_breaker):
        """Test de la réinitialisation."""
        # Génère de l'output pour modifier l'état
        circuit_breaker.record_output("some output\n")

        # Reset
        circuit_breaker.reset()

        assert circuit_breaker.state == CircuitBreakerState.CLOSED
        assert circuit_breaker.attempts == 0
        assert circuit_breaker.last_trigger is None
        assert circuit_breaker.is_open is False

    def test_disabled_config(self, default_context):
        """Test avec circuit breaker désactivé."""
        config = CircuitBreakerConfig(enabled=False)
        cb = CircuitBreaker(config=config, context=default_context)

        # Les méthodes ne devraient rien faire
        result = cb.record_output("x" * 1000000 + "\n")  # Huge output
        assert result is None

        result = cb.check_inactivity()
        assert result is None

        result = cb.check_task_stagnation()
        assert result is None

        assert cb.is_open is False


class TestCircuitBreakerSpecialCases:
    """Tests pour les cas spéciaux du circuit breaker."""

    def test_pr_phase_120s_timeout(self):
        """Test que la phase PR a un timeout de 120s."""
        config = CircuitBreakerConfig(enabled=True, inactivity_timeout=60)
        context = CircuitBreakerContext(phase=Phase.PR)
        cb = CircuitBreaker(config=config, context=context)

        # Accès à la méthode privée pour tester
        effective_timeout = cb._get_effective_inactivity_timeout()
        assert effective_timeout == 120

    def test_test_command_300s_timeout(self):
        """Test que la commande de test a un timeout de 300s."""
        config = CircuitBreakerConfig(enabled=True, inactivity_timeout=60)
        context = CircuitBreakerContext(
            phase=Phase.QA,
            test_command="npm test",
        )
        cb = CircuitBreaker(config=config, context=context)

        # Simule l'exécution de la commande de test
        cb.record_output("Running npm test...\n")
        cb.record_output("npm test in progress\n")

        effective_timeout = cb._get_effective_inactivity_timeout()
        assert effective_timeout == 300

    def test_normal_phase_default_timeout(self):
        """Test que les phases normales ont le timeout par défaut."""
        config = CircuitBreakerConfig(enabled=True, inactivity_timeout=60)
        context = CircuitBreakerContext(phase=Phase.IMPLEMENTATION)
        cb = CircuitBreaker(config=config, context=context)

        effective_timeout = cb._get_effective_inactivity_timeout()
        assert effective_timeout == 60


class TestCircuitBreakerThreadSafety:
    """Tests de thread safety pour le circuit breaker."""

    def test_concurrent_record_output(self):
        """Test d'appels concurrents à record_output."""
        config = CircuitBreakerConfig(
            enabled=True,
            max_output_size=10000,
            max_attempts=100,  # Beaucoup de tentatives pour éviter trip prématuré
        )
        context = CircuitBreakerContext(phase=Phase.IMPLEMENTATION)
        cb = CircuitBreaker(config=config, context=context)

        errors = []
        num_threads = 10
        iterations = 100

        def worker():
            try:
                for _ in range(iterations):
                    cb.record_output(f"output from thread\n")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0

    def test_concurrent_checks(self):
        """Test d'appels concurrents aux méthodes de vérification."""
        config = CircuitBreakerConfig(
            enabled=True,
            inactivity_timeout=100,  # Long timeout
            task_stagnation_timeout=100,
        )
        context = CircuitBreakerContext(phase=Phase.IMPLEMENTATION)
        cb = CircuitBreaker(config=config, context=context)

        errors = []

        def worker_inactivity():
            try:
                for _ in range(100):
                    cb.check_inactivity()
            except Exception as e:
                errors.append(e)

        def worker_stagnation():
            try:
                for _ in range(100):
                    cb.check_task_stagnation()
            except Exception as e:
                errors.append(e)

        threads = []
        for _ in range(5):
            threads.append(threading.Thread(target=worker_inactivity))
            threads.append(threading.Thread(target=worker_stagnation))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0


class TestTriggerType:
    """Tests pour l'enum TriggerType."""

    def test_trigger_values(self):
        """Test des valeurs de TriggerType."""
        assert TriggerType.INACTIVITY.value == "inactivity"
        assert TriggerType.REPEATED_ERROR.value == "repeated_error"
        assert TriggerType.TASK_STAGNATION.value == "task_stagnation"
        assert TriggerType.OUTPUT_SIZE.value == "output_size"


class TestCircuitBreakerState:
    """Tests pour l'enum CircuitBreakerState."""

    def test_state_values(self):
        """Test des valeurs de CircuitBreakerState."""
        assert CircuitBreakerState.CLOSED.value == "closed"
        assert CircuitBreakerState.OPEN.value == "open"
