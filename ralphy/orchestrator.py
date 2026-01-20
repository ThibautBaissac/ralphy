"""Orchestrateur principal du workflow Ralphy."""

from pathlib import Path
from typing import Callable, Optional

from ralphy.agents import DevAgent, PRAgent, QAAgent, SpecAgent
from ralphy.config import ProjectConfig, ensure_ralph_dir, ensure_specs_dir, load_config
from ralphy.logger import get_logger
from ralphy.progress import ProgressDisplay
from ralphy.state import Phase, StateManager
from ralphy.validation import HumanValidator


class WorkflowError(Exception):
    """Erreur dans le workflow."""

    pass


class TransitionError(WorkflowError):
    """Erreur de transition de phase invalide."""

    pass


class Orchestrator:
    """Orchestrateur du workflow Ralphy."""

    def __init__(
        self,
        project_path: Path,
        on_output: Optional[Callable[[str], None]] = None,
        show_progress: bool = True,
    ):
        self.project_path = project_path.resolve()
        self._user_output = on_output
        self.config = load_config(self.project_path)
        self.state_manager = StateManager(self.project_path)
        self.validator = HumanValidator()
        self.logger = get_logger()
        self._aborted = False
        self._qa_agent: Optional[QAAgent] = None
        self._show_progress = show_progress
        self._progress_display: Optional[ProgressDisplay] = None

        # Configure output callback
        if show_progress:
            self._progress_display = ProgressDisplay()
            self.on_output = self._progress_output
        else:
            self.on_output = on_output or self._default_output

    def _default_output(self, text: str) -> None:
        """Handler de sortie par défaut."""
        self.logger.stream(text)

    def _progress_output(self, text: str) -> None:
        """Handler de sortie avec mise à jour du progress display."""
        if self._progress_display and self._progress_display.is_active:
            self._progress_display.process_output(text)
        if self._user_output:
            self._user_output(text)

    def _spec_artifacts_valid(self) -> bool:
        """Vérifie si les artéfacts de la phase SPECIFICATION sont valides.

        Vérifie que SPEC.md et TASKS.md existent et ont une taille minimale
        indiquant un contenu substantiel.
        """
        spec_path = self.project_path / "specs" / "SPEC.md"
        tasks_path = self.project_path / "specs" / "TASKS.md"
        return (
            spec_path.exists()
            and tasks_path.exists()
            and spec_path.stat().st_size > 1000
            and tasks_path.stat().st_size > 500
        )

    def _qa_artifacts_valid(self) -> bool:
        """Vérifie si les artéfacts de la phase QA sont valides.

        Vérifie que QA_REPORT.md existe et a une taille minimale.
        """
        qa_path = self.project_path / "specs" / "QA_REPORT.md"
        return qa_path.exists() and qa_path.stat().st_size > 500

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

        phase_order = [
            Phase.SPECIFICATION,
            Phase.AWAITING_SPEC_VALIDATION,
            Phase.IMPLEMENTATION,
            Phase.QA,
            Phase.AWAITING_QA_VALIDATION,
            Phase.PR,
        ]

        try:
            phase_idx = phase_order.index(phase)
            resume_idx = phase_order.index(resume_from)
            return phase_idx < resume_idx
        except ValueError:
            return False

    def _restore_task_count(self) -> None:
        """Restaure le compteur de tâches depuis TASKS.md lors d'une reprise.

        Utilisé quand on saute la phase SPECIFICATION pour restaurer
        le nombre de tâches complétées et le total dans l'état.
        Parse TASKS.md pour compter les tâches marquées comme 'completed'.
        """
        from ralphy.agents import DevAgent

        agent = DevAgent(
            project_path=self.project_path,
            config=self.config,
        )
        completed, total = agent.count_task_status()
        if total > 0:
            self.state_manager.update_tasks(completed, total)

    def _start_phase_progress(self, phase_name: str, total_tasks: int = 0) -> None:
        """Démarre l'affichage de progression pour une phase."""
        if self._progress_display and self._show_progress:
            self.logger.set_live_mode(True)
            self._progress_display.start(phase_name, total_tasks)

    def _stop_phase_progress(self) -> None:
        """Arrête l'affichage de progression."""
        if self._progress_display and self._progress_display.is_active:
            self._progress_display.stop()
            self.logger.set_live_mode(False)

    def run(self, fresh: bool = False) -> bool:
        """Exécute le workflow complet.

        Args:
            fresh: Si True, force un redémarrage complet sans reprise.
        """
        try:
            self._validate_prerequisites()
            ensure_ralph_dir(self.project_path)
            ensure_specs_dir(self.project_path)

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
                    return False
                self.state_manager.mark_phase_completed(Phase.SPECIFICATION)
            else:
                self.logger.info("Phase SPECIFICATION déjà complétée, passage à la suite")
                self._restore_task_count()

            # Validation #1
            if not self._should_skip_phase(Phase.AWAITING_SPEC_VALIDATION, resume_phase):
                if not self._run_spec_validation():
                    return False
                self.state_manager.mark_phase_completed(Phase.AWAITING_SPEC_VALIDATION)
            else:
                self.logger.info("Validation SPEC déjà effectuée, passage à la suite")

            # Phase 2: Implementation
            if not self._should_skip_phase(Phase.IMPLEMENTATION, resume_phase):
                if not self._run_implementation_phase():
                    return False
                self.state_manager.mark_phase_completed(Phase.IMPLEMENTATION)
            else:
                self.logger.info("Phase IMPLEMENTATION déjà complétée, passage à la suite")

            # Phase 3: QA
            if not self._should_skip_phase(Phase.QA, resume_phase):
                if not self._run_qa_phase():
                    return False
                self.state_manager.mark_phase_completed(Phase.QA)
            else:
                self.logger.info("Phase QA déjà complétée, passage à la suite")

            # Validation #2
            if not self._should_skip_phase(Phase.AWAITING_QA_VALIDATION, resume_phase):
                if not self._run_qa_validation():
                    return False
                self.state_manager.mark_phase_completed(Phase.AWAITING_QA_VALIDATION)
            else:
                self.logger.info("Validation QA déjà effectuée, passage à la suite")

            # Phase 4: PR
            if not self._should_skip_phase(Phase.PR, resume_phase):
                if not self._run_pr_phase():
                    return False
                self.state_manager.mark_phase_completed(Phase.PR)

            self._safe_transition(Phase.COMPLETED)
            self.logger.success("Workflow terminé avec succès!")
            return True

        except WorkflowError as e:
            self.state_manager.set_failed(str(e))
            self.logger.error(f"Workflow échoué: {e}")
            return False
        except KeyboardInterrupt:
            self.state_manager.set_failed("Interrompu par l'utilisateur")
            self.logger.warn("Workflow interrompu")
            return False

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
        prd_path = self.project_path / "PRD.md"
        if not prd_path.exists():
            raise WorkflowError(f"PRD.md non trouvé dans {self.project_path}")

        # Vérifie que le projet n'est pas déjà en cours
        if self.state_manager.is_running():
            raise WorkflowError("Un workflow est déjà en cours")

    def _run_specification_phase(self) -> bool:
        """Exécute la phase de spécification."""
        self.logger.phase("SPECIFICATION")
        self._safe_transition(Phase.SPECIFICATION)

        self._start_phase_progress("SPECIFICATION")

        try:
            agent = SpecAgent(
                project_path=self.project_path,
                config=self.config,
                on_output=self.on_output,
                model=self.config.models.specification,
            )

            result = agent.run(timeout=self.config.timeouts.specification)

            if not result.success:
                self.state_manager.set_failed(result.error_message)
                return False

            # Compte les tâches générées
            tasks_count = agent.count_tasks()
            self.state_manager.update_tasks(0, tasks_count)

            return True
        finally:
            self._stop_phase_progress()

    def _run_spec_validation(self) -> bool:
        """Demande la validation des specs."""
        self._safe_transition(Phase.AWAITING_SPEC_VALIDATION)

        tasks_count = self.state_manager.state.tasks_total
        validation = self.validator.request_spec_validation(
            self.project_path,
            tasks_count,
        )

        if not validation.approved:
            self._safe_transition(Phase.REJECTED)
            return False

        return True

    def _run_implementation_phase(self) -> bool:
        """Exécute la phase d'implémentation."""
        self.logger.phase("IMPLEMENTATION")
        self._safe_transition(Phase.IMPLEMENTATION)

        # Récupère le nombre de tâches pour la progress bar
        completed_tasks = self.state_manager.state.tasks_completed
        total_tasks = self.state_manager.state.tasks_total
        self._start_phase_progress("IMPLEMENTATION", total_tasks)

        # Si on reprend avec des tâches déjà complétées, met à jour l'affichage
        if completed_tasks > 0 and self._progress_display:
            self._progress_display.update_tasks(completed_tasks, total_tasks)

        try:
            agent = DevAgent(
                project_path=self.project_path,
                config=self.config,
                on_output=self.on_output,
                model=self.config.models.implementation,
            )

            result = agent.run(timeout=self.config.timeouts.implementation)

            if self._aborted:
                return False

            if not result.success:
                self.state_manager.set_failed(result.error_message)
                return False

            # Met à jour le compteur de tâches
            completed, total = agent.count_task_status()
            self.state_manager.update_tasks(completed, total)

            return True
        finally:
            self._stop_phase_progress()

    def _run_qa_phase(self) -> bool:
        """Exécute la phase QA."""
        self.logger.phase("QA")
        self._safe_transition(Phase.QA)

        self._start_phase_progress("QA")

        try:
            self._qa_agent = QAAgent(
                project_path=self.project_path,
                config=self.config,
                on_output=self.on_output,
                model=self.config.models.qa,
            )

            result = self._qa_agent.run(timeout=self.config.timeouts.qa)

            if not result.success:
                self.state_manager.set_failed(result.error_message)
                return False

            return True
        finally:
            self._stop_phase_progress()

    def _run_qa_validation(self) -> bool:
        """Demande la validation du rapport QA."""
        self._safe_transition(Phase.AWAITING_QA_VALIDATION)

        # Réutilise l'instance QAAgent créée dans _run_qa_phase()
        if self._qa_agent is None:
            # Fallback si appelé hors séquence normale (ne devrait pas arriver)
            self._qa_agent = QAAgent(
                project_path=self.project_path,
                config=self.config,
                model=self.config.models.qa,
            )

        qa_summary = self._qa_agent.get_report_summary()

        validation = self.validator.request_qa_validation(
            self.project_path,
            qa_summary,
        )

        if not validation.approved:
            self._safe_transition(Phase.REJECTED)
            return False

        return True

    def _run_pr_phase(self) -> bool:
        """Exécute la phase de création de PR."""
        self.logger.phase("PR")
        self._safe_transition(Phase.PR)

        self._start_phase_progress("PR")

        try:
            agent = PRAgent(
                project_path=self.project_path,
                config=self.config,
                on_output=self.on_output,
                model=self.config.models.pr,
            )

            result = agent.run(timeout=self.config.timeouts.pr)

            if not result.success:
                self.state_manager.set_failed(result.error_message)
                return False

            # Log l'URL de la PR
            for f in result.files_generated:
                if f.startswith("PR:"):
                    self.logger.success(f)

            return True
        finally:
            self._stop_phase_progress()
