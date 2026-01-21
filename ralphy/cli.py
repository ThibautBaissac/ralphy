"""Interface CLI pour Ralphy."""

import sys
from importlib import resources
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from ralphy import __version__
from ralphy.claude import (
    abort_running_claude,
    check_claude_installed,
    check_gh_installed,
    check_git_installed,
)
from ralphy.config import load_config
from ralphy.logger import get_logger
from ralphy.orchestrator import Orchestrator
from ralphy.state import Phase, StateManager


# Liste des fichiers de prompts à copier
PROMPT_FILES = [
    "spec_agent.md",
    "dev_agent.md",
    "qa_agent.md",
    "pr_agent.md",
]


def _generate_prompt_header(prompt_file: str) -> str:
    """Génère un header documentant les placeholders disponibles pour un prompt.

    Args:
        prompt_file: Nom du fichier de prompt (ex: spec_agent.md)

    Returns:
        Header markdown avec documentation des placeholders.
    """
    # Placeholders communs à tous les prompts
    common_placeholders = """
| Placeholder | Description |
|-------------|-------------|
| `{{project_name}}` | Nom du projet |
| `{{language}}` | Stack technique (depuis config.yaml) |
| `{{test_command}}` | Commande de test (depuis config.yaml) |
"""

    # Placeholders spécifiques par agent
    specific_placeholders = {
        "spec_agent.md": """| `{{prd_content}}` | Contenu de PRD.md |
""",
        "dev_agent.md": """| `{{spec_content}}` | Contenu de SPEC.md |
| `{{tasks_content}}` | Contenu de TASKS.md |
| `{{resume_instruction}}` | Instructions de reprise (vide si nouvelle session) |
""",
        "qa_agent.md": """| `{{spec_content}}` | Contenu de SPEC.md |
""",
        "pr_agent.md": """| `{{branch_name}}` | Nom de la branche à créer |
| `{{qa_report}}` | Contenu du rapport QA |
| `{{spec_content}}` | Contenu de SPEC.md |
""",
    }

    agent_name = prompt_file.replace("_agent.md", "").replace("_", " ").title()
    specific = specific_placeholders.get(prompt_file, "")

    return f"""<!--
=============================================================================
CUSTOM PROMPT TEMPLATE - {agent_name} Agent
=============================================================================

Ce fichier est un template de prompt personnalisé pour Ralphy.
Modifiez-le pour adapter le comportement de l'agent à votre stack/projet.

IMPORTANT: Ce prompt DOIT contenir l'instruction "EXIT_SIGNAL" pour que
l'agent puisse signaler la fin de son exécution.

Placeholders disponibles (remplacés automatiquement à l'exécution):
{common_placeholders}{specific}
Documentation: https://github.com/your-org/ralphy#custom-prompts
=============================================================================
-->

"""


console = Console()


@click.group()
@click.version_option(version=__version__, prog_name="ralphy")
def main():
    """Ralphy - Transforme un PRD en Pull Request."""
    pass


@main.command()
@click.argument("project_path", type=click.Path(exists=True, file_okay=False, resolve_path=True))
@click.option("--no-progress", is_flag=True, help="Désactive l'affichage de progression")
@click.option("--fresh", is_flag=True, help="Force un redémarrage complet sans reprise")
def start(project_path: str, no_progress: bool, fresh: bool):
    """Démarre un workflow Ralphy.

    PROJECT_PATH: Chemin vers le projet contenant PRD.md

    Par défaut, si le workflow a été interrompu, il reprendra depuis la
    dernière phase complétée. Utilisez --fresh pour forcer un redémarrage complet.
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
    success = orchestrator.run(fresh=fresh)

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

    table = Table(title=f"Statut Ralphy - {project.name}")
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

    if state.last_completed_phase:
        table.add_row("Dernière phase complétée", f"[cyan]{state.last_completed_phase}[/cyan]")

    if state.error_message:
        table.add_row("Erreur", f"[red]{state.error_message}[/red]")

    console.print(table)

    # Hint pour redémarrer si le workflow est terminé en échec
    if state.phase in (Phase.FAILED, Phase.REJECTED):
        console.print()
        if state.last_completed_phase:
            console.print(
                f"[dim]💡 Pour reprendre le workflow: [cyan]ralphy start {project}[/cyan][/dim]"
            )
            console.print(
                f"[dim]💡 Pour redémarrer de zéro: [cyan]ralphy start {project} --fresh[/cyan][/dim]"
            )
        else:
            console.print(
                f"[dim]💡 Pour relancer le workflow: [cyan]ralphy start {project}[/cyan][/dim]"
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


@main.command("init-prompts")
@click.argument("project_path", type=click.Path(exists=True, file_okay=False, resolve_path=True), required=False)
@click.option("--force", is_flag=True, help="Écrase les prompts existants")
def init_prompts(project_path: str = None, force: bool = False):
    """Initialise les templates de prompts personnalisés.

    Copie les templates de prompts par défaut dans .ralphy/prompts/ du projet.
    Ces templates peuvent ensuite être modifiés pour adapter Ralphy à votre stack.

    PROJECT_PATH: Chemin vers le projet (défaut: répertoire courant)

    Utilisez --force pour écraser les prompts existants.
    """
    project = Path(project_path) if project_path else Path.cwd()
    logger = get_logger()

    # Crée le répertoire .ralphy/prompts/ s'il n'existe pas
    prompts_dir = project / ".ralphy" / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)

    copied = 0
    skipped = 0

    for prompt_file in PROMPT_FILES:
        dest_path = prompts_dir / prompt_file

        # Skip si fichier existe et pas --force
        if dest_path.exists() and not force:
            logger.warn(f"Skipping {prompt_file} (exists, use --force to overwrite)")
            skipped += 1
            continue

        # Charge le contenu depuis le package
        try:
            original_content = resources.files("ralphy.prompts").joinpath(prompt_file).read_text(encoding="utf-8")
        except (FileNotFoundError, TypeError):
            logger.error(f"Template {prompt_file} not found in package")
            continue

        # Ajoute le header documentant les placeholders
        header = _generate_prompt_header(prompt_file)
        content = header + original_content

        # Écrit le fichier
        dest_path.write_text(content, encoding="utf-8")
        logger.info(f"Created {prompt_file}")
        copied += 1

    # Résumé
    console.print()
    if copied > 0:
        console.print(f"[green]✓[/green] {copied} prompt(s) copied to {prompts_dir}")
    if skipped > 0:
        console.print(f"[yellow]![/yellow] {skipped} prompt(s) skipped (use --force to overwrite)")

    if copied > 0:
        console.print()
        console.print("[dim]Edit these files to customize Ralphy for your project.[/dim]")
        console.print("[dim]Remember: prompts must contain EXIT_SIGNAL instruction.[/dim]")


if __name__ == "__main__":
    main()
