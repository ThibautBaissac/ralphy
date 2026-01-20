"""Gestion de l'état du workflow Ralphy."""

import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional


class Phase(str, Enum):
    """Phases du workflow."""

    IDLE = "idle"
    SPECIFICATION = "specification"
    AWAITING_SPEC_VALIDATION = "awaiting_spec_validation"
    IMPLEMENTATION = "implementation"
    QA = "qa"
    AWAITING_QA_VALIDATION = "awaiting_qa_validation"
    PR = "pr"
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"


class Status(str, Enum):
    """Statuts possibles."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


# Transitions valides entre phases
VALID_TRANSITIONS: dict[Phase, list[Phase]] = {
    Phase.IDLE: [Phase.SPECIFICATION],
    Phase.SPECIFICATION: [Phase.AWAITING_SPEC_VALIDATION, Phase.FAILED],
    Phase.AWAITING_SPEC_VALIDATION: [Phase.IMPLEMENTATION, Phase.REJECTED],
    Phase.IMPLEMENTATION: [Phase.QA, Phase.FAILED],
    Phase.QA: [Phase.AWAITING_QA_VALIDATION, Phase.FAILED],
    Phase.AWAITING_QA_VALIDATION: [Phase.PR, Phase.REJECTED],
    Phase.PR: [Phase.COMPLETED, Phase.FAILED],
    Phase.COMPLETED: [],
    Phase.FAILED: [Phase.IDLE],  # Permet de redémarrer
    Phase.REJECTED: [Phase.IDLE],  # Permet de redémarrer
}


@dataclass
class WorkflowState:
    """État du workflow."""

    phase: Phase = Phase.IDLE
    status: Status = Status.PENDING
    started_at: Optional[str] = None
    tasks_completed: int = 0
    tasks_total: int = 0
    error_message: Optional[str] = None
    # Circuit breaker state tracking
    circuit_breaker_state: str = "closed"
    circuit_breaker_attempts: int = 0
    circuit_breaker_last_trigger: Optional[str] = None

    @classmethod
    def from_dict(cls, data: dict) -> "WorkflowState":
        """Crée un état depuis un dictionnaire."""
        return cls(
            phase=Phase(data.get("phase", "idle")),
            status=Status(data.get("status", "pending")),
            started_at=data.get("started_at"),
            tasks_completed=data.get("tasks_completed", 0),
            tasks_total=data.get("tasks_total", 0),
            error_message=data.get("error_message"),
            circuit_breaker_state=data.get("circuit_breaker_state", "closed"),
            circuit_breaker_attempts=data.get("circuit_breaker_attempts", 0),
            circuit_breaker_last_trigger=data.get("circuit_breaker_last_trigger"),
        )

    def to_dict(self) -> dict:
        """Convertit l'état en dictionnaire."""
        return {
            "phase": self.phase.value,
            "status": self.status.value,
            "started_at": self.started_at,
            "tasks_completed": self.tasks_completed,
            "tasks_total": self.tasks_total,
            "error_message": self.error_message,
            "circuit_breaker_state": self.circuit_breaker_state,
            "circuit_breaker_attempts": self.circuit_breaker_attempts,
            "circuit_breaker_last_trigger": self.circuit_breaker_last_trigger,
        }


class StateManager:
    """Gestionnaire d'état du workflow."""

    def __init__(self, project_path: Path):
        self.project_path = project_path
        self.state_file = project_path / ".ralphy" / "state.json"
        self._state: Optional[WorkflowState] = None

    @property
    def state(self) -> WorkflowState:
        """Retourne l'état actuel, le charge si nécessaire."""
        if self._state is None:
            self._state = self.load()
        return self._state

    def load(self) -> WorkflowState:
        """Charge l'état depuis le fichier."""
        if not self.state_file.exists():
            return WorkflowState()

        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if not content:
                    # Fichier vide - retourne état par défaut
                    return WorkflowState()
                data = json.loads(content)
            return WorkflowState.from_dict(data)
        except (json.JSONDecodeError, ValueError):
            # Fichier corrompu - retourne état par défaut
            return WorkflowState()

    def save(self) -> None:
        """Sauvegarde l'état dans le fichier."""
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(self.state.to_dict(), f, indent=2)

    def can_transition(self, new_phase: Phase) -> bool:
        """Vérifie si la transition vers la nouvelle phase est valide."""
        return new_phase in VALID_TRANSITIONS.get(self.state.phase, [])

    def transition(self, new_phase: Phase) -> bool:
        """Effectue une transition de phase si valide."""
        if not self.can_transition(new_phase):
            return False

        self.state.phase = new_phase
        self.state.status = Status.RUNNING if new_phase not in (
            Phase.COMPLETED, Phase.FAILED, Phase.REJECTED,
            Phase.AWAITING_SPEC_VALIDATION, Phase.AWAITING_QA_VALIDATION
        ) else Status.PENDING

        if new_phase == Phase.SPECIFICATION:
            self.state.started_at = datetime.now().isoformat()

        self.save()
        return True

    def set_running(self) -> None:
        """Définit le statut comme running."""
        self.state.status = Status.RUNNING
        self.save()

    def set_completed(self) -> None:
        """Définit le statut comme completed."""
        self.state.status = Status.COMPLETED
        self.save()

    def set_failed(self, error_message: Optional[str] = None) -> None:
        """Définit le statut comme failed."""
        self.state.status = Status.FAILED
        self.state.phase = Phase.FAILED
        self.state.error_message = error_message
        self.save()

    def update_tasks(self, completed: int, total: int) -> None:
        """Met à jour le compteur de tâches."""
        self.state.tasks_completed = completed
        self.state.tasks_total = total
        self.save()

    def reset_circuit_breaker(self) -> None:
        """Réinitialise le circuit breaker."""
        self.state.circuit_breaker_state = "closed"
        self.state.circuit_breaker_attempts = 0
        self.state.circuit_breaker_last_trigger = None
        self.save()

    def reset(self) -> None:
        """Réinitialise l'état."""
        self._state = WorkflowState()
        self.save()

    def is_idle(self) -> bool:
        """Vérifie si le workflow est au repos."""
        return self.state.phase == Phase.IDLE

    def is_running(self) -> bool:
        """Vérifie si le workflow est en cours."""
        return self.state.phase in (
            Phase.SPECIFICATION,
            Phase.IMPLEMENTATION,
            Phase.QA,
            Phase.PR,
        )

    def is_awaiting_validation(self) -> bool:
        """Vérifie si le workflow attend une validation."""
        return self.state.phase in (
            Phase.AWAITING_SPEC_VALIDATION,
            Phase.AWAITING_QA_VALIDATION,
        )

    def is_finished(self) -> bool:
        """Vérifie si le workflow est terminé."""
        return self.state.phase in (
            Phase.COMPLETED,
            Phase.FAILED,
            Phase.REJECTED,
        )
