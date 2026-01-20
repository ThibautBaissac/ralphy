"""Gestion de la configuration projet Ralphy."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


@dataclass
class TimeoutConfig:
    """Configuration des timeouts en secondes.

    Chaque phase a son propre timeout spécifique.
    Le timeout `agent` sert de valeur par défaut si aucun timeout
    n'est spécifié lors de l'appel à agent.run().
    """

    specification: int = 1800  # 30 min - Phase 1
    implementation: int = 14400  # 4h - Phase 2
    qa: int = 1800  # 30 min - Phase 3
    pr: int = 600  # 10 min - Phase 4
    agent: int = 300  # 5 min - Fallback par défaut (utilisé par BaseAgent.run)


@dataclass
class RetryConfig:
    """Configuration des retries pour les agents.

    Les retries sont déclenchés sur timeout ou erreur (return code != 0).
    Les échecs d'EXIT_SIGNAL ne déclenchent pas de retry.
    """

    max_attempts: int = 2  # Nombre total de tentatives (1 = pas de retry)
    delay_seconds: int = 5  # Délai entre les tentatives


@dataclass
class CircuitBreakerConfig:
    """Configuration du circuit breaker.

    Le circuit breaker protège contre les boucles infinies et agents bloqués.
    Il surveille 4 triggers:
    - inactivity: Aucune sortie pendant X secondes
    - repeated_error: Même erreur répétée X fois
    - task_stagnation: Pas de tâche complétée pendant X secondes
    - output_size: Sortie dépassant X bytes
    """

    enabled: bool = True
    inactivity_timeout: int = 60  # secondes
    max_repeated_errors: int = 3
    task_stagnation_timeout: int = 600  # 10 minutes
    max_output_size: int = 524288  # 500KB
    max_attempts: int = 3  # Warnings avant trip


@dataclass
class ModelConfig:
    """Configuration des modèles Claude par phase.

    Utilise des alias ('sonnet', 'opus', 'haiku') ou noms complets de modèle.
    Par défaut, toutes les phases utilisent 'sonnet'.
    """

    specification: str = "sonnet"  # Phase 1: spec-agent
    implementation: str = "sonnet"  # Phase 2: dev-agent
    qa: str = "sonnet"  # Phase 3: qa-agent
    pr: str = "sonnet"  # Phase 4: pr-agent


@dataclass
class StackConfig:
    """Configuration de la stack technique."""

    language: str = "typescript"
    test_command: str = "npm test"


@dataclass
class ProjectConfig:
    """Configuration complète du projet."""

    name: str = "my-project"
    timeouts: TimeoutConfig = field(default_factory=TimeoutConfig)
    models: ModelConfig = field(default_factory=ModelConfig)
    stack: StackConfig = field(default_factory=StackConfig)
    retry: RetryConfig = field(default_factory=RetryConfig)
    circuit_breaker: CircuitBreakerConfig = field(default_factory=CircuitBreakerConfig)

    @classmethod
    def from_dict(cls, data: dict) -> "ProjectConfig":
        """Crée une config depuis un dictionnaire."""
        timeouts_data = data.get("timeouts", {})
        models_data = data.get("models", {})
        stack_data = data.get("stack", {})
        project_data = data.get("project", {})
        retry_data = data.get("retry", {})
        cb_data = data.get("circuit_breaker", {})

        timeouts = TimeoutConfig(
            specification=timeouts_data.get("specification", 1800),
            implementation=timeouts_data.get("implementation", 14400),
            qa=timeouts_data.get("qa", 1800),
            pr=timeouts_data.get("pr", 600),
            agent=timeouts_data.get("agent", 300),
        )

        models = ModelConfig(
            specification=models_data.get("specification", "sonnet"),
            implementation=models_data.get("implementation", "sonnet"),
            qa=models_data.get("qa", "sonnet"),
            pr=models_data.get("pr", "sonnet"),
        )

        stack = StackConfig(
            language=stack_data.get("language", "typescript"),
            test_command=stack_data.get("test_command", "npm test"),
        )

        retry = RetryConfig(
            max_attempts=retry_data.get("max_attempts", 2),
            delay_seconds=retry_data.get("delay_seconds", 5),
        )

        circuit_breaker = CircuitBreakerConfig(
            enabled=cb_data.get("enabled", True),
            inactivity_timeout=cb_data.get("inactivity_timeout", 60),
            max_repeated_errors=cb_data.get("max_repeated_errors", 3),
            task_stagnation_timeout=cb_data.get("task_stagnation_timeout", 600),
            max_output_size=cb_data.get("max_output_size", 524288),
            max_attempts=cb_data.get("max_attempts", 3),
        )

        return cls(
            name=project_data.get("name", "my-project"),
            timeouts=timeouts,
            models=models,
            stack=stack,
            retry=retry,
            circuit_breaker=circuit_breaker,
        )

    def to_dict(self) -> dict:
        """Convertit la config en dictionnaire."""
        return {
            "project": {"name": self.name},
            "timeouts": {
                "specification": self.timeouts.specification,
                "implementation": self.timeouts.implementation,
                "qa": self.timeouts.qa,
                "pr": self.timeouts.pr,
                "agent": self.timeouts.agent,
            },
            "models": {
                "specification": self.models.specification,
                "implementation": self.models.implementation,
                "qa": self.models.qa,
                "pr": self.models.pr,
            },
            "stack": {
                "language": self.stack.language,
                "test_command": self.stack.test_command,
            },
            "retry": {
                "max_attempts": self.retry.max_attempts,
                "delay_seconds": self.retry.delay_seconds,
            },
            "circuit_breaker": {
                "enabled": self.circuit_breaker.enabled,
                "inactivity_timeout": self.circuit_breaker.inactivity_timeout,
                "max_repeated_errors": self.circuit_breaker.max_repeated_errors,
                "task_stagnation_timeout": self.circuit_breaker.task_stagnation_timeout,
                "max_output_size": self.circuit_breaker.max_output_size,
                "max_attempts": self.circuit_breaker.max_attempts,
            },
        }


def load_config(project_path: Path) -> ProjectConfig:
    """Charge la configuration depuis .ralphy/config.yaml."""
    config_path = project_path / ".ralphy" / "config.yaml"

    if not config_path.exists():
        return ProjectConfig()

    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    return ProjectConfig.from_dict(data)


def save_config(project_path: Path, config: ProjectConfig) -> None:
    """Sauvegarde la configuration dans .ralphy/config.yaml."""
    ralph_dir = project_path / ".ralphy"
    ralph_dir.mkdir(parents=True, exist_ok=True)

    config_path = ralph_dir / "config.yaml"
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(config.to_dict(), f, default_flow_style=False, allow_unicode=True)


def ensure_ralph_dir(project_path: Path) -> Path:
    """S'assure que le dossier .ralphy existe et retourne son chemin."""
    ralph_dir = project_path / ".ralphy"
    ralph_dir.mkdir(parents=True, exist_ok=True)
    return ralph_dir


def ensure_specs_dir(project_path: Path) -> Path:
    """S'assure que le dossier specs existe et retourne son chemin."""
    specs_dir = project_path / "specs"
    specs_dir.mkdir(parents=True, exist_ok=True)
    return specs_dir
