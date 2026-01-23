"""Main orchestrator for the Ralphy workflow."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Optional, Type

from ralphy.agents import DevAgent, PRAgent, QAAgent, SpecAgent
from ralphy.agents.qa import parse_qa_report_summary
from ralphy.agents.base import AgentResult, BaseAgent
from ralphy.config import ProjectConfig, ensure_feature_dir, ensure_ralph_dir, load_config
from ralphy.constants import (
    MIN_QA_REPORT_FILE_SIZE_BYTES,
    MIN_SPEC_FILE_SIZE_BYTES,
    MIN_TASKS_FILE_SIZE_BYTES,
)
from ralphy.journal import WorkflowJournal
from ralphy.logger import get_logger
from ralphy.progress import Activity, ProgressDisplay
from ralphy.state import PHASE_ORDER, Phase, StateManager
from ralphy.validation import HumanValidator

if TYPE_CHECKING:
    from ralphy.claude import TokenUsage


class WorkflowError(Exception):
    """Error in the workflow."""

    pass


class TransitionError(WorkflowError):
    """Error for invalid phase transition."""

    pass


class Orchestrator:
    """Central coordinator for the Ralphy workflow.

    This class orchestrates the entire workflow lifecycle, managing:
    - Phase transitions via StateManager (SPECIFICATION → IMPLEMENTATION → QA → PR)
    - Agent execution with timeout enforcement and retry logic
    - Human validation gates between phases
    - Progress display coordination (Rich Live UI)
    - Workflow journaling for audit and resume capability
    - Task-level checkpointing for mid-implementation resume

    Design note: While this class has multiple responsibilities, they are all
    related to workflow coordination - its single reason to change is "how
    the workflow is orchestrated." Extracting these into separate classes
    would fragment the coordination logic without clear benefit, as they
    all share state (feature_dir, config, state_manager) and work together
    as a cohesive unit during workflow execution.
    """

    def __init__(
        self,
        project_path: Path,
        feature_name: str,
        on_output: Optional[Callable[[str], None]] = None,
        show_progress: bool = True,
    ):
        self.project_path = project_path.resolve()
        self.feature_name = feature_name
        self.feature_dir = project_path / "docs" / "features" / feature_name
        self._user_output = on_output
        self.config = load_config(self.project_path)
        self.state_manager = StateManager(self.project_path, feature_name)
        self.validator = HumanValidator()
        self.logger = get_logger()
        self._aborted = False
        self._show_progress = show_progress
        self._progress_display: Optional[ProgressDisplay] = None

        # Workflow journal for progress persistence
        self._journal = WorkflowJournal(self.feature_dir, feature_name)

        # Track current phase for journal end_phase calls
        self._current_phase_model: str = ""
        self._current_phase_timeout: int = 0
        self._current_phase_tasks_total: int = 0
        self._last_token_usage: Optional[TokenUsage] = None
        self._last_cost: float = 0.0

        # Cached DevAgent for query operations (count_task_status, get_next_pending_task_after)
        self._cached_dev_agent: Optional[DevAgent] = None

        # Configure output callback
        if show_progress:
            self._progress_display = ProgressDisplay(
                on_task_event=self._on_task_event,
                on_activity=self._on_activity,
            )
            self.on_output = self._progress_output
        else:
            self.on_output = on_output or self._default_output

    def _default_output(self, text: str) -> None:
        """Default output handler."""
        self.logger.stream(text)

    @property
    def _dev_agent_for_queries(self) -> DevAgent:
        """Lazily create and cache DevAgent for query operations.

        This agent is reused for count_task_status() and get_next_pending_task_after()
        to avoid repeated instantiation. For run() operations, create fresh instances
        with appropriate callbacks.
        """
        if self._cached_dev_agent is None:
            self._cached_dev_agent = DevAgent(
                project_path=self.project_path,
                config=self.config,
                feature_dir=self.feature_dir,
            )
        return self._cached_dev_agent

    def _progress_output(self, text: str) -> None:
        """Handler de sortie avec mise à jour du progress display."""
        if self._progress_display and self._progress_display.is_active:
            self._progress_display.process_output(text)
        if self._user_output:
            self._user_output(text)

    def _on_task_event(
        self, event_type: str, task_id: str | None, task_name: str | None
    ) -> None:
        """Callback appelé lors des événements de tâche (start/complete)."""
        if event_type == "start":
            if task_name:
                self.logger.task_start(f"Tâche {task_id}: {task_name}")
            elif task_id:
                self.logger.task_start(f"Tâche {task_id}")
            # Checkpoint task as in_progress
            if task_id:
                self.state_manager.checkpoint_task(task_id, "in_progress")
            # Log to journal
            self._journal.record_task_event(event_type, task_id, task_name)
        elif event_type == "complete":
            if task_name:
                self.logger.task_complete(f"Tâche {task_id}: {task_name}")
            elif task_id:
                self.logger.task_complete(f"Tâche {task_id}")
            else:
                self.logger.task_complete("Tâche complétée")
            # Checkpoint task as completed and update task counter
            if task_id:
                self.state_manager.checkpoint_task(task_id, "completed")
                completed, total = self._dev_agent_for_queries.count_task_status()
                self.state_manager.update_tasks(completed, total)
                # Sync progress display with authoritative file-based count
                if self._progress_display and self._progress_display.is_active:
                    self._progress_display.update_tasks(completed, total)
            # Log to journal
            self._journal.record_task_event(event_type, task_id, task_name)

    def _on_activity(self, activity: Activity) -> None:
        """Callback appelé lors de la détection d'une activité."""
        self._journal.record_activity(activity)

    def _on_token_update(self, usage: TokenUsage, cost: float) -> None:
        """Callback appelé lors de la mise à jour des tokens."""
        if self._progress_display and self._progress_display.is_active:
            self._progress_display.update_token_usage(usage, cost)
        # Track for phase end summary
        self._last_token_usage = usage
        self._last_cost = cost
        # Log to journal
        self._journal.record_token_update(usage, cost)

    def _spec_artifacts_valid(self) -> bool:
        """Vérifie si les artéfacts de la phase SPECIFICATION sont valides.

        Vérifie que SPEC.md et TASKS.md existent et ont une taille minimale
        indiquant un contenu substantiel.
        """
        spec_path = self.feature_dir / "SPEC.md"
        tasks_path = self.feature_dir / "TASKS.md"
        return (
            spec_path.exists()
            and tasks_path.exists()
            and spec_path.stat().st_size > MIN_SPEC_FILE_SIZE_BYTES
            and tasks_path.stat().st_size > MIN_TASKS_FILE_SIZE_BYTES
        )

    def _qa_artifacts_valid(self) -> bool:
        """Vérifie si les artéfacts de la phase QA sont valides.

        Vérifie que QA_REPORT.md existe et a une taille minimale.
        """
        qa_path = self.feature_dir / "QA_REPORT.md"
        return qa_path.exists() and qa_path.stat().st_size > MIN_QA_REPORT_FILE_SIZE_BYTES

    def _get_qa_report_summary(self) -> dict:
        """Extract QA summary directly from QA_REPORT.md file.

        This decouples the validation phase from the QAAgent instance,
        allowing workflow resume from AWAITING_QA_VALIDATION phase.
        """
        qa_path = self.feature_dir / "QA_REPORT.md"
        if not qa_path.exists():
            return parse_qa_report_summary(None)

        content = qa_path.read_text(encoding="utf-8")
        return parse_qa_report_summary(content)

    def _determine_resume_phase(self) -> Optional[Phase]:
        """Détermine la phase depuis laquelle reprendre le workflow.

        Basé sur last_completed_phase et la validation des artéfacts correspondants.
        Retourne None si aucune reprise n'est possible (redémarrage complet).
        """
        last = self.state_manager.state.last_completed_phase
        if not last:
            return None

        try:
            completed_phase = Phase(last)
        except ValueError:
            return None

        # Détermine la prochaine phase basée sur ce qui a été complété
        # et valide que les artéfacts requis sont présents
        if completed_phase == Phase.SPECIFICATION:
            if self._spec_artifacts_valid():
                return Phase.AWAITING_SPEC_VALIDATION
        elif completed_phase == Phase.AWAITING_SPEC_VALIDATION:
            if self._spec_artifacts_valid():
                return Phase.IMPLEMENTATION
        elif completed_phase == Phase.IMPLEMENTATION:
            if self._spec_artifacts_valid():
                return Phase.QA
        elif completed_phase == Phase.QA:
            if self._spec_artifacts_valid() and self._qa_artifacts_valid():
                return Phase.AWAITING_QA_VALIDATION
        elif completed_phase == Phase.AWAITING_QA_VALIDATION:
            if self._spec_artifacts_valid() and self._qa_artifacts_valid():
                return Phase.PR

        return None

    def _should_skip_phase(self, phase: Phase, resume_from: Optional[Phase]) -> bool:
        """Détermine si une phase doit être sautée lors de la reprise.

        Args:
            phase: La phase à évaluer
            resume_from: La phase depuis laquelle on reprend (None = pas de reprise)

        Returns:
            True si la phase doit être sautée, False sinon
        """
        if not resume_from:
            return False

        try:
            phase_idx = PHASE_ORDER.index(phase)
            resume_idx = PHASE_ORDER.index(resume_from)
            return phase_idx < resume_idx
        except ValueError:
            return False

    def _restore_task_count(self) -> None:
        """Restaure le compteur de tâches depuis TASKS.md lors d'une reprise.

        Utilisé quand on saute la phase SPECIFICATION pour restaurer
        le nombre de tâches complétées et le total dans l'état.
        Parse TASKS.md pour compter les tâches marquées comme 'completed'.
        """
        completed, total = self._dev_agent_for_queries.count_task_status()
        if total > 0:
            self.state_manager.update_tasks(completed, total)

    def _start_phase_progress(
        self,
        phase_name: str,
        total_tasks: int = 0,
        model: str = "",
        timeout: int = 0,
    ) -> None:
        """Démarre l'affichage de progression pour une phase."""
        # Track phase info for journal end_phase calls
        self._current_phase_model = model
        self._current_phase_timeout = timeout
        self._current_phase_tasks_total = total_tasks
        self._last_token_usage = None
        self._last_cost = 0.0

        # Log to journal
        self._journal.start_phase(
            phase=phase_name,
            model=model,
            timeout=timeout,
            tasks_total=total_tasks,
        )

        if self._progress_display and self._show_progress:
            self.logger.set_live_mode(True)
            self._progress_display.start(
                phase_name,
                total_tasks,
                model=model,
                timeout=timeout,
                feature_name=self.feature_name,
            )

    def _stop_phase_progress(
        self,
        outcome: str = "unknown",
        tasks_completed: int = 0,
    ) -> None:
        """Arrête l'affichage de progression et log la fin de phase.

        Args:
            outcome: Phase outcome (e.g., "success", "failed", "timeout")
            tasks_completed: Number of tasks completed in this phase
        """
        # Log phase end to journal
        token_usage_dict = None
        if self._last_token_usage:
            token_usage_dict = {
                "input_tokens": self._last_token_usage.input_tokens,
                "output_tokens": self._last_token_usage.output_tokens,
                "cache_read_tokens": self._last_token_usage.cache_read_tokens,
                "cache_creation_tokens": self._last_token_usage.cache_creation_tokens,
            }
        self._journal.end_phase(
            outcome=outcome,
            token_usage=token_usage_dict,
            cost=self._last_cost,
            tasks_completed=tasks_completed,
        )

        if self._progress_display and self._progress_display.is_active:
            self._progress_display.stop()
            self.logger.set_live_mode(False)

    def run(self, fresh: bool = False) -> bool:
        """Exécute le workflow complet.

        Args:
            fresh: Si True, force un redémarrage complet sans reprise.
        """
        workflow_outcome = "unknown"
        try:
            # Start journal at workflow begin
            self._journal.start_workflow(fresh=fresh)

            self._validate_prerequisites()
            ensure_ralph_dir(self.project_path)
            ensure_feature_dir(self.project_path, self.feature_name)

            # Détermine si on peut reprendre depuis une phase précédente
            resume_phase = None
            if self.state_manager.state.phase in (Phase.FAILED, Phase.REJECTED):
                if not fresh:
                    resume_phase = self._determine_resume_phase()
                    if resume_phase:
                        self.logger.info(
                            f"Reprise du workflow depuis: {resume_phase.value}"
                        )
                self._safe_transition(Phase.IDLE)

            # Phase 1: Specification
            if not self._should_skip_phase(Phase.SPECIFICATION, resume_phase):
                if not self._run_specification_phase():
                    workflow_outcome = "failed"
                    return False
                self.state_manager.mark_phase_completed(Phase.SPECIFICATION)
            else:
                self.logger.info("Phase SPECIFICATION déjà complétée, passage à la suite")
                self._restore_task_count()

            # Validation #1
            if not self._should_skip_phase(Phase.AWAITING_SPEC_VALIDATION, resume_phase):
                if not self._run_spec_validation():
                    workflow_outcome = "rejected"
                    return False
                self.state_manager.mark_phase_completed(Phase.AWAITING_SPEC_VALIDATION)
            else:
                self.logger.info("Validation SPEC déjà effectuée, passage à la suite")

            # Phase 2: Implementation
            if not self._should_skip_phase(Phase.IMPLEMENTATION, resume_phase):
                if not self._run_implementation_phase():
                    workflow_outcome = "failed"
                    return False
                self.state_manager.mark_phase_completed(Phase.IMPLEMENTATION)
            else:
                self.logger.info("Phase IMPLEMENTATION déjà complétée, passage à la suite")

            # Phase 3: QA
            if not self._should_skip_phase(Phase.QA, resume_phase):
                if not self._run_qa_phase():
                    workflow_outcome = "failed"
                    return False
                self.state_manager.mark_phase_completed(Phase.QA)
            else:
                self.logger.info("Phase QA déjà complétée, passage à la suite")

            # Validation #2
            if not self._should_skip_phase(Phase.AWAITING_QA_VALIDATION, resume_phase):
                if not self._run_qa_validation():
                    workflow_outcome = "rejected"
                    return False
                self.state_manager.mark_phase_completed(Phase.AWAITING_QA_VALIDATION)
            else:
                self.logger.info("Validation QA déjà effectuée, passage à la suite")

            # Phase 4: PR
            if not self._should_skip_phase(Phase.PR, resume_phase):
                if not self._run_pr_phase():
                    workflow_outcome = "failed"
                    return False
                self.state_manager.mark_phase_completed(Phase.PR)

            self._safe_transition(Phase.COMPLETED)
            self.logger.success("Workflow terminé avec succès!")
            workflow_outcome = "completed"
            return True

        except WorkflowError as e:
            self.state_manager.set_failed(str(e))
            self.logger.error(f"Workflow échoué: {e}")
            self._journal.record_error(str(e), "workflow_error")
            workflow_outcome = "failed"
            return False
        except KeyboardInterrupt:
            self.state_manager.set_failed("Interrompu par l'utilisateur")
            self.logger.warn("Workflow interrompu")
            workflow_outcome = "aborted"
            return False
        finally:
            # End journal with final outcome
            self._journal.end_workflow(workflow_outcome)

    def abort(self) -> None:
        """Abort le workflow en cours."""
        self._aborted = True
        self.state_manager.set_failed("Avorté par l'utilisateur")

    def _safe_transition(self, new_phase: Phase) -> None:
        """Effectue une transition de phase avec vérification.

        Raises:
            TransitionError: Si la transition est invalide.
        """
        current_phase = self.state_manager.state.phase
        if not self.state_manager.transition(new_phase):
            raise TransitionError(
                f"Transition invalide: {current_phase.value} -> {new_phase.value}"
            )

    def _validate_prerequisites(self) -> None:
        """Vérifie les prérequis."""
        prd_path = self.feature_dir / "PRD.md"
        if not prd_path.exists():
            raise WorkflowError(f"PRD.md non trouvé dans {self.feature_dir}")

        # Vérifie que le projet n'est pas déjà en cours
        if self.state_manager.is_running():
            raise WorkflowError("Un workflow est déjà en cours")

    def _get_implementation_resume_task(self) -> str | None:
        """Détermine si l'implémentation doit reprendre depuis une tâche spécifique.

        Returns:
            ID de la tâche depuis laquelle reprendre, ou None pour démarrer du début.
        """
        resume_task_id = self.state_manager.get_resume_task_id()
        if not resume_task_id:
            return None

        agent = self._dev_agent_for_queries
        next_task = agent.get_next_pending_task_after(resume_task_id)

        if next_task:
            return next_task

        # All tasks might be completed - check before returning resume_task_id
        completed, total = agent.count_task_status()
        if completed >= total:
            return None

        return resume_task_id

    def _run_agent_phase(
        self,
        phase: Phase,
        phase_name: str,
        agent_class: Type[BaseAgent],
        timeout: int,
        model: str,
        total_tasks: int = 0,
        agent_kwargs: Optional[dict[str, Any]] = None,
        run_kwargs: Optional[dict[str, Any]] = None,
        post_run: Optional[Callable[[AgentResult, BaseAgent], None]] = None,
        pre_start: Optional[Callable[[], None]] = None,
    ) -> bool:
        """Generic method to run an agent phase.

        Consolidates common logic: logging, transition, progress display,
        agent creation, execution, and error handling.

        Args:
            phase: The workflow phase to transition to.
            phase_name: Display name for logging and progress.
            agent_class: The agent class to instantiate.
            timeout: Timeout in seconds for agent execution.
            model: Model to use for the agent.
            total_tasks: Number of tasks for progress display (0 = no task bar).
            agent_kwargs: Additional kwargs for agent constructor.
            run_kwargs: Additional kwargs for agent.run().
            post_run: Optional callback after successful run (receives result and agent).
            pre_start: Optional callback after progress display starts, before agent runs.

        Returns:
            True if phase completed successfully, False otherwise.
        """
        self.logger.phase(phase_name)
        self._safe_transition(phase)

        self._start_phase_progress(
            phase_name,
            total_tasks=total_tasks,
            model=model,
            timeout=timeout,
        )

        # Optional pre-start hook (e.g., restore progress for resumed tasks)
        if pre_start:
            pre_start()

        phase_outcome = "unknown"
        tasks_completed = 0
        try:
            # Build agent with common + custom kwargs
            kwargs: dict[str, Any] = {
                "project_path": self.project_path,
                "config": self.config,
                "on_output": self.on_output,
                "model": model,
                "feature_dir": self.feature_dir,
                "on_token_update": self._on_token_update,
            }
            if agent_kwargs:
                kwargs.update(agent_kwargs)

            agent = agent_class(**kwargs)

            # Run agent with timeout + custom kwargs
            run_args: dict[str, Any] = {"timeout": timeout}
            if run_kwargs:
                run_args.update(run_kwargs)

            result = agent.run(**run_args)

            if self._aborted:
                phase_outcome = "aborted"
                tasks_completed = self.state_manager.state.tasks_completed
                return False

            if not result.success:
                self.state_manager.set_failed(result.error_message)
                phase_outcome = "failed"
                tasks_completed = self.state_manager.state.tasks_completed
                return False

            # Optional post-run callback
            if post_run:
                post_run(result, agent)

            phase_outcome = "success"
            tasks_completed = self.state_manager.state.tasks_completed
            return True
        finally:
            self._stop_phase_progress(outcome=phase_outcome, tasks_completed=tasks_completed)

    def _run_specification_phase(self) -> bool:
        """Exécute la phase de spécification."""

        def on_spec_complete(result: AgentResult, agent: BaseAgent) -> None:
            """Post-run callback for specification phase."""
            spec_agent = agent  # type: SpecAgent
            tasks_count = spec_agent.count_tasks()
            self.state_manager.update_tasks(0, tasks_count)
            self.state_manager.clear_task_checkpoints()

        return self._run_agent_phase(
            phase=Phase.SPECIFICATION,
            phase_name="SPECIFICATION",
            agent_class=SpecAgent,
            timeout=self.config.timeouts.specification,
            model=self.config.models.specification,
            post_run=on_spec_complete,
        )

    def _run_spec_validation(self) -> bool:
        """Demande la validation des specs."""
        self._safe_transition(Phase.AWAITING_SPEC_VALIDATION)

        tasks_count = self.state_manager.state.tasks_total
        validation = self.validator.request_spec_validation(
            self.feature_dir,
            tasks_count,
        )

        # Log validation event to journal
        self._journal.record_validation(
            phase="SPECIFICATION",
            approved=validation.approved,
            feedback=validation.comment,
        )

        if not validation.approved:
            self._safe_transition(Phase.REJECTED)
            return False

        return True

    def _run_implementation_phase(self) -> bool:
        """Exécute la phase d'implémentation.

        This phase has special handling for:
        - Task resume from checkpoint
        - Progress display with task count
        - Post-run task status update
        """
        # Determine if we should resume from a specific task
        resume_task_id = self._get_implementation_resume_task()
        if resume_task_id:
            self.logger.info(f"Reprise de l'implémentation depuis la tâche {resume_task_id}")

        # Pre-run: restore progress display for resumed tasks
        completed_tasks = self.state_manager.state.tasks_completed
        total_tasks = self.state_manager.state.tasks_total

        def pre_start_hook() -> None:
            """Update progress display with existing task count if resuming."""
            if completed_tasks > 0 and self._progress_display:
                self._progress_display.update_tasks(completed_tasks, total_tasks)

        def on_impl_complete(result: AgentResult, agent: BaseAgent) -> None:
            """Post-run callback to update task counter."""
            if self._aborted:
                return
            dev_agent = agent  # type: DevAgent
            completed, total = dev_agent.count_task_status()
            self.state_manager.update_tasks(completed, total)

        return self._run_agent_phase(
            phase=Phase.IMPLEMENTATION,
            phase_name="IMPLEMENTATION",
            agent_class=DevAgent,
            timeout=self.config.timeouts.implementation,
            model=self.config.models.implementation,
            total_tasks=total_tasks,
            run_kwargs={"start_from_task": resume_task_id},
            post_run=on_impl_complete,
            pre_start=pre_start_hook,
        )

    def _run_qa_phase(self) -> bool:
        """Exécute la phase QA."""
        return self._run_agent_phase(
            phase=Phase.QA,
            phase_name="QA",
            agent_class=QAAgent,
            timeout=self.config.timeouts.qa,
            model=self.config.models.qa,
        )

    def _run_qa_validation(self) -> bool:
        """Demande la validation du rapport QA."""
        self._safe_transition(Phase.AWAITING_QA_VALIDATION)

        # Read summary directly from file to support workflow resume
        qa_summary = self._get_qa_report_summary()

        validation = self.validator.request_qa_validation(
            self.feature_dir,
            qa_summary,
        )

        # Log validation event to journal
        self._journal.record_validation(
            phase="QA",
            approved=validation.approved,
            feedback=validation.comment,
        )

        if not validation.approved:
            self._safe_transition(Phase.REJECTED)
            return False

        return True

    def _run_pr_phase(self) -> bool:
        """Exécute la phase de création de PR."""

        def on_pr_complete(result: AgentResult, agent: BaseAgent) -> None:
            """Post-run callback for PR phase."""
            for f in result.files_generated:
                if f.startswith("PR:"):
                    self.logger.success(f)

        return self._run_agent_phase(
            phase=Phase.PR,
            phase_name="PR",
            agent_class=PRAgent,
            timeout=self.config.timeouts.pr,
            model=self.config.models.pr,
            agent_kwargs={"feature_name": self.feature_name},
            post_run=on_pr_complete,
        )
