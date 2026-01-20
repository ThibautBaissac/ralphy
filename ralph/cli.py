"""Interface CLI pour RalphWiggum."""

import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from ralph import __version__
from ralph.claude import (
    abort_running_claude,
    check_claude_installed,
    check_gh_installed,
    check_git_installed,
)
from ralph.config import load_config
from ralph.logger import get_logger
from ralph.orchestrator import Orchestrator
from ralph.state import Phase, StateManager


console = Console()


@click.group()
@click.version_option(version=__version__, prog_name="ralph")
def main():
    """RalphWiggum - Transforme un PRD en Pull Request."""
    pass


@main.command()
@click.argument("project_path", type=click.Path(exists=True, file_okay=False, resolve_path=True))
@click.option("--no-progress", is_flag=True, help="Désactive l'affichage de progression")
def start(project_path: str, no_progress: bool):
    """Démarre un workflow RalphWiggum.

    PROJECT_PATH: Chemin vers le projet contenant PRD.md
    """
    project = Path(project_path)
    logger = get_logger()
    show_progress = not no_progress

    # Vérifications préliminaires
    if not check_claude_installed():
        logger.error("Claude Code CLI non trouvé. Installez-le avec: npm install -g @anthropic-ai/claude-code")
        sys.exit(1)

    if not check_git_installed():
        logger.error("Git non trouvé. Installez Git: https://git-scm.com/")
        sys.exit(1)

    if not check_gh_installed():
        logger.error("GitHub CLI (gh) non trouvé. Installez-le: https://cli.github.com/")
        sys.exit(1)

    prd_path = project / "PRD.md"
    if not prd_path.exists():
        logger.error(f"PRD.md non trouvé dans {project}")
        sys.exit(1)

    # Vérifie si un workflow est déjà en cours
    state_manager = StateManager(project)
    if state_manager.is_running():
        logger.warn(f"Un workflow est déjà en cours (phase: {state_manager.state.phase.value})")
        if not click.confirm("Voulez-vous le réinitialiser ?", default=False):
            sys.exit(0)
        state_manager.reset()

    # Lance l'orchestrateur
    logger.info(f"Démarrage du workflow pour: {project}")
    logger.newline()

    orchestrator = Orchestrator(project, show_progress=show_progress)
    success = orchestrator.run()

    sys.exit(0 if success else 1)


@main.command()
@click.argument("project_path", type=click.Path(exists=True, file_okay=False, resolve_path=True), required=False)
def status(project_path: str = None):
    """Affiche le statut du workflow.

    PROJECT_PATH: Chemin vers le projet (défaut: répertoire courant)
    """
    project = Path(project_path) if project_path else Path.cwd()
    state_manager = StateManager(project)
    state = state_manager.state

    table = Table(title=f"Statut RalphWiggum - {project.name}")
    table.add_column("Propriété", style="cyan")
    table.add_column("Valeur", style="green")

    # Style selon la phase
    phase_style = "green"
    if state.phase in (Phase.FAILED, Phase.REJECTED):
        phase_style = "red"
    elif state.phase in (Phase.AWAITING_SPEC_VALIDATION, Phase.AWAITING_QA_VALIDATION):
        phase_style = "yellow"

    table.add_row("Phase", f"[{phase_style}]{state.phase.value}[/{phase_style}]")
    table.add_row("Statut", state.status.value)

    if state.started_at:
        table.add_row("Démarré", state.started_at)

    if state.tasks_total > 0:
        progress = f"{state.tasks_completed}/{state.tasks_total}"
        table.add_row("Tâches", progress)

    if state.error_message:
        table.add_row("Erreur", f"[red]{state.error_message}[/red]")

    console.print(table)

    # Hint pour redémarrer si le workflow est terminé en échec
    if state.phase in (Phase.FAILED, Phase.REJECTED):
        console.print()
        console.print(
            f"[dim]💡 Pour relancer le workflow: [cyan]ralph start {project}[/cyan][/dim]"
        )


@main.command()
@click.argument("project_path", type=click.Path(exists=True, file_okay=False, resolve_path=True), required=False)
def abort(project_path: str = None):
    """Abort le workflow en cours.

    PROJECT_PATH: Chemin vers le projet (défaut: répertoire courant)
    """
    project = Path(project_path) if project_path else Path.cwd()
    state_manager = StateManager(project)
    logger = get_logger()

    # Vérifie si le workflow est actif (running ou en attente de validation)
    if not state_manager.is_running() and not state_manager.is_awaiting_validation():
        logger.warn("Aucun workflow en cours")
        return

    # Interrompt le process Claude s'il est en cours (pas de process pendant validation)
    if state_manager.is_running():
        abort_running_claude(project)

    state_manager.set_failed("Avorté par l'utilisateur")
    logger.info("Workflow avorté")


@main.command()
@click.argument("project_path", type=click.Path(exists=True, file_okay=False, resolve_path=True), required=False)
def reset(project_path: str = None):
    """Réinitialise l'état du workflow.

    PROJECT_PATH: Chemin vers le projet (défaut: répertoire courant)
    """
    project = Path(project_path) if project_path else Path.cwd()
    state_manager = StateManager(project)
    logger = get_logger()

    if click.confirm("Réinitialiser l'état du workflow ?", default=False):
        state_manager.reset()
        logger.info("État réinitialisé")


if __name__ == "__main__":
    main()
