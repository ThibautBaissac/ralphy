"""Classe de base pour les agents RalphWiggum."""

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Callable, Optional

from ralph.circuit_breaker import CircuitBreaker, CircuitBreakerContext
from ralph.claude import ClaudeResponse, ClaudeRunner
from ralph.config import ProjectConfig
from ralph.logger import get_logger
from ralph.state import Phase


@dataclass
class AgentResult:
    """Résultat d'exécution d'un agent."""

    success: bool
    output: str
    files_generated: list[str]
    error_message: Optional[str] = None


class BaseAgent(ABC):
    """Classe abstraite pour tous les agents."""

    name: str = "base-agent"
    prompt_file: str = ""

    def __init__(
        self,
        project_path: Path,
        config: ProjectConfig,
        on_output: Optional[Callable[[str], None]] = None,
    ):
        self.project_path = project_path
        self.config = config
        self.on_output = on_output
        self.logger = get_logger()

    @abstractmethod
    def build_prompt(self) -> str:
        """Construit le prompt pour l'agent."""
        pass

    @abstractmethod
    def parse_output(self, response: ClaudeResponse) -> AgentResult:
        """Parse la sortie de Claude et retourne le résultat."""
        pass

    def load_prompt_template(self) -> str:
        """Charge le template de prompt depuis le package."""
        try:
            return resources.files("ralph.prompts").joinpath(self.prompt_file).read_text(encoding="utf-8")
        except (FileNotFoundError, TypeError):
            self.logger.error(f"Template {self.prompt_file} non trouvé")
            return ""

    def read_file(self, filename: str) -> Optional[str]:
        """Lit un fichier du projet."""
        filepath = self.project_path / filename
        if filepath.exists():
            return filepath.read_text(encoding="utf-8")
        return None

    def _should_retry(self, response: ClaudeResponse) -> bool:
        """Détermine si un retry est justifié.

        Retry sur:
        - Timeout
        - Code retour non-zéro (erreur Claude)
        - Circuit breaker triggered

        Pas de retry si:
        - EXIT_SIGNAL manquant (c'est un problème de prompt/agent, pas transitoire)
        - Succès
        """
        return (
            response.timed_out
            or response.return_code != 0
            or response.circuit_breaker_triggered
        )

    def run(
        self, timeout: Optional[int] = None, phase: Optional[Phase] = None
    ) -> AgentResult:
        """Exécute l'agent avec retry automatique et circuit breaker.

        Args:
            timeout: Timeout en secondes. Si non spécifié, utilise
                     config.timeouts.agent comme fallback.
            phase: Phase du workflow pour le contexte du circuit breaker.

        Returns:
            AgentResult avec le résultat de l'exécution.

        Le retry est déclenché sur timeout, erreur (return code != 0),
        ou circuit breaker triggered.
        Le nombre de tentatives et le délai sont configurables via
        config.retry.max_attempts et config.retry.delay_seconds.
        """
        self.logger.agent(self.name, "started")

        prompt = self.build_prompt()
        if not prompt:
            return AgentResult(
                success=False,
                output="",
                files_generated=[],
                error_message="Impossible de construire le prompt",
            )

        # Utilise le timeout spécifique ou le fallback agent
        agent_timeout = timeout or self.config.timeouts.agent
        max_attempts = self.config.retry.max_attempts
        delay = self.config.retry.delay_seconds

        # Configuration du circuit breaker
        cb_config = self.config.circuit_breaker
        cb_context = CircuitBreakerContext(
            phase=phase or Phase.IMPLEMENTATION,
            is_dev_agent=(self.name == "dev-agent"),
            test_command=self.config.stack.test_command,
        )

        last_response: Optional[ClaudeResponse] = None
        last_error: Optional[str] = None

        for attempt in range(1, max_attempts + 1):
            if attempt > 1:
                self.logger.agent(self.name, f"retry {attempt}/{max_attempts}")
                time.sleep(delay)

            # Crée le circuit breaker si activé (reset à chaque tentative)
            circuit_breaker = None
            if cb_config.enabled:
                circuit_breaker = CircuitBreaker(
                    config=cb_config,
                    context=cb_context,
                    on_warning=lambda t, a: self.logger.warn(
                        f"Circuit breaker: {t.value} ({a}/{cb_config.max_attempts})"
                    ),
                    on_trip=lambda t: self.logger.error(
                        f"Circuit breaker: OPEN - {t.value}"
                    ),
                )

            runner = ClaudeRunner(
                working_dir=self.project_path,
                timeout=agent_timeout,
                on_output=self.on_output,
                circuit_breaker=circuit_breaker,
            )

            response = runner.run(prompt)
            last_response = response

            # Circuit breaker triggered - retry possible
            if response.circuit_breaker_triggered:
                trigger_type = (
                    circuit_breaker.last_trigger.value
                    if circuit_breaker and circuit_breaker.last_trigger
                    else "unknown"
                )
                last_error = f"Circuit breaker: {trigger_type}"
                if attempt < max_attempts:
                    self.logger.warn(f"{self.name}: {last_error}, retry...")
                    continue
                self.logger.agent(self.name, "circuit_breaker_open")
                return AgentResult(
                    success=False,
                    output=response.output,
                    files_generated=[],
                    error_message=last_error,
                )

            # Timeout - retry possible
            if response.timed_out:
                last_error = f"Timeout après {agent_timeout}s"
                if attempt < max_attempts:
                    self.logger.warn(f"{self.name}: {last_error}, retry...")
                    continue
                self.logger.agent(self.name, "timeout")
                return AgentResult(
                    success=False,
                    output=response.output,
                    files_generated=[],
                    error_message=last_error,
                )

            # Erreur Claude - retry possible
            if response.return_code != 0:
                last_error = f"Code retour: {response.return_code}"
                if attempt < max_attempts:
                    self.logger.warn(f"{self.name}: {last_error}, retry...")
                    continue
                self.logger.agent(self.name, "failed")
                return AgentResult(
                    success=False,
                    output=response.output,
                    files_generated=[],
                    error_message=last_error,
                )

            # Claude a répondu correctement - pas de retry nécessaire
            break

        # Parse le résultat (pas de retry sur échec de parsing/EXIT_SIGNAL)
        result = self.parse_output(last_response)

        if result.success:
            self.logger.agent(self.name, "completed")
        else:
            self.logger.agent(self.name, f"failed: {result.error_message}")

        return result
