"""Gestion de la configuration projet Ralphy."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from ralphy.constants import (
    AGENT_TIMEOUT_SECONDS,
    CB_INACTIVITY_TIMEOUT_SECONDS,
    CB_MAX_ATTEMPTS,
    CB_MAX_OUTPUT_SIZE_BYTES,
    CB_MAX_REPEATED_ERRORS,
    CB_TASK_STAGNATION_TIMEOUT_SECONDS,
    DEFAULT_RETRY_ATTEMPTS,
    DEFAULT_RETRY_DELAY_SECONDS,
    FEATURE_NAME_PATTERN,
    IMPL_TIMEOUT_SECONDS,
    PR_TIMEOUT_SECONDS,
    QA_TIMEOUT_SECONDS,
    SPEC_TIMEOUT_SECONDS,
)
from ralphy.logger import get_logger

# Whitelist of allowed model names to prevent command injection
ALLOWED_MODELS = frozenset({
    "sonnet",
    "opus",
    "haiku",
    "claude-sonnet-4-5-20250929",
    "claude-opus-4-5-20251101",
    "claude-haiku-4-5-20251001",
})


def validate_model(model: str) -> str:
    """Validate and return model name, or default to sonnet.

    Args:
        model: The model name from config

    Returns:
        The validated model name, or 'sonnet' if invalid
    """
    if model in ALLOWED_MODELS:
        return model
    logger = get_logger()
    logger.warn(f"Invalid model '{model}' - falling back to 'sonnet'")
    return "sonnet"


@dataclass
class TimeoutConfig:
    """Configuration des timeouts en secondes.

    Chaque phase a son propre timeout spécifique.
    Le timeout `agent` sert de valeur par défaut si aucun timeout
    n'est spécifié lors de l'appel à agent.run().
    """

    specification: int = SPEC_TIMEOUT_SECONDS  # 30 min - Phase 1
    implementation: int = IMPL_TIMEOUT_SECONDS  # 4h - Phase 2
    qa: int = QA_TIMEOUT_SECONDS  # 30 min - Phase 3
    pr: int = PR_TIMEOUT_SECONDS  # 10 min - Phase 4
    agent: int = AGENT_TIMEOUT_SECONDS  # 5 min - Fallback (BaseAgent.run)


@dataclass
class RetryConfig:
    """Configuration des retries pour les agents.

    Les retries sont déclenchés sur timeout ou erreur (return code != 0).
    Les échecs d'EXIT_SIGNAL ne déclenchent pas de retry.
    """

    max_attempts: int = DEFAULT_RETRY_ATTEMPTS  # Total attempts (1 = no retry)
    delay_seconds: int = DEFAULT_RETRY_DELAY_SECONDS  # Delay between retries


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
    inactivity_timeout: int = CB_INACTIVITY_TIMEOUT_SECONDS
    max_repeated_errors: int = CB_MAX_REPEATED_ERRORS
    task_stagnation_timeout: int = CB_TASK_STAGNATION_TIMEOUT_SECONDS  # 10 minutes
    max_output_size: int = CB_MAX_OUTPUT_SIZE_BYTES  # 500KB
    max_attempts: int = CB_MAX_ATTEMPTS  # Warnings before trip


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
            specification=timeouts_data.get("specification", SPEC_TIMEOUT_SECONDS),
            implementation=timeouts_data.get("implementation", IMPL_TIMEOUT_SECONDS),
            qa=timeouts_data.get("qa", QA_TIMEOUT_SECONDS),
            pr=timeouts_data.get("pr", PR_TIMEOUT_SECONDS),
            agent=timeouts_data.get("agent", AGENT_TIMEOUT_SECONDS),
        )

        models = ModelConfig(
            specification=validate_model(models_data.get("specification", "sonnet")),
            implementation=validate_model(models_data.get("implementation", "sonnet")),
            qa=validate_model(models_data.get("qa", "sonnet")),
            pr=validate_model(models_data.get("pr", "sonnet")),
        )

        stack = StackConfig(
            language=stack_data.get("language", "typescript"),
            test_command=stack_data.get("test_command", "npm test"),
        )

        retry = RetryConfig(
            max_attempts=retry_data.get("max_attempts", DEFAULT_RETRY_ATTEMPTS),
            delay_seconds=retry_data.get("delay_seconds", DEFAULT_RETRY_DELAY_SECONDS),
        )

        circuit_breaker = CircuitBreakerConfig(
            enabled=cb_data.get("enabled", True),
            inactivity_timeout=cb_data.get("inactivity_timeout", CB_INACTIVITY_TIMEOUT_SECONDS),
            max_repeated_errors=cb_data.get("max_repeated_errors", CB_MAX_REPEATED_ERRORS),
            task_stagnation_timeout=cb_data.get("task_stagnation_timeout", CB_TASK_STAGNATION_TIMEOUT_SECONDS),
            max_output_size=cb_data.get("max_output_size", CB_MAX_OUTPUT_SIZE_BYTES),
            max_attempts=cb_data.get("max_attempts", CB_MAX_ATTEMPTS),
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


def _validate_feature_name(feature_name: str) -> None:
    """Validate feature name to prevent path traversal attacks.

    Args:
        feature_name: The feature name to validate.

    Raises:
        ValueError: If the feature name contains invalid characters or patterns.
    """
    # Check for path traversal patterns
    if ".." in feature_name:
        raise ValueError(f"Invalid feature name: contains '..': {feature_name}")
    if "/" in feature_name:
        raise ValueError(f"Invalid feature name: contains '/': {feature_name}")
    if "\\" in feature_name:
        raise ValueError(f"Invalid feature name: contains '\\': {feature_name}")

    # Check pattern - must start with alphanumeric, contain only safe characters
    if not FEATURE_NAME_PATTERN.match(feature_name):
        raise ValueError(
            f"Invalid feature name format: {feature_name}. "
            "Must start with alphanumeric and contain only alphanumeric, hyphens, or underscores."
        )


def get_feature_dir(project_path: Path, feature_name: str) -> Path:
    """Returns the feature directory path: docs/features/<feature-name>/

    Args:
        project_path: Root path of the project
        feature_name: Name of the feature

    Returns:
        Path to the feature directory

    Raises:
        ValueError: If feature_name contains invalid characters or path traversal attempts.
    """
    _validate_feature_name(feature_name)
    return project_path / "docs" / "features" / feature_name


def ensure_feature_dir(project_path: Path, feature_name: str) -> Path:
    """Creates and returns the feature directory.

    Args:
        project_path: Root path of the project
        feature_name: Name of the feature

    Returns:
        Path to the created feature directory

    Raises:
        ValueError: If feature_name contains invalid characters or path traversal attempts.
    """
    feature_dir = get_feature_dir(project_path, feature_name)
    feature_dir.mkdir(parents=True, exist_ok=True)
    return feature_dir
