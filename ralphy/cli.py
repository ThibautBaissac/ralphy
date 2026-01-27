"""CLI interface for Ralphy."""

import re
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
from ralphy.config import get_feature_dir, load_config
from ralphy.constants import FEATURE_NAME_PATTERN
from ralphy.logger import get_logger
from ralphy.orchestrator import Orchestrator
from ralphy.state import Phase, StateManager
from ralphy.templates import (
    AGENT_FILES,
    generate_config_template,
    generate_quick_prd,
)


def _check_dependencies() -> list[tuple[str, str]]:
    """Check for required dependencies.

    Returns:
        List of (name, install_hint) tuples for missing dependencies.
    """
    missing = []
    if not check_claude_installed():
        missing.append(("Claude Code CLI", "npm install -g @anthropic-ai/claude-code"))
    if not check_git_installed():
        missing.append(("Git", "https://git-scm.com/"))
    if not check_gh_installed():
        missing.append(("GitHub CLI (gh)", "https://cli.github.com/"))
    return missing


def description_to_feature_name(description: str, max_length: int = 50) -> str:
    """Convert a description string to a valid feature name slug.

    Args:
        description: The feature description (e.g., "implement auth with devise")
        max_length: Maximum length for the slug (default 50)

    Returns:
        A valid feature name slug (e.g., "implement-auth-with-devise")

    Raises:
        ValueError: If the description cannot be converted to a valid feature name
    """
    import unicodedata

    if not description or not description.strip():
        raise ValueError("Cannot derive valid feature name from empty description")

    # Normalize unicode, lowercase, replace non-alphanumeric with hyphens
    slug = unicodedata.normalize("NFKD", description)
    slug = slug.encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
    slug = re.sub(r"-+", "-", slug)

    # Truncate without breaking mid-word
    if len(slug) > max_length:
        slug = slug[:max_length].rsplit("-", 1)[0]

    if not slug or not FEATURE_NAME_PATTERN.match(slug):
        raise ValueError(f"Cannot derive valid feature name from: {description}")

    return slug


console = Console()


@click.group()
@click.version_option(version=__version__, prog_name="ralphy")
def main():
    """Ralphy - Transforms a PRD into a Pull Request."""
    pass


@main.command()
@click.argument("feature_or_description", type=str)
@click.option("--no-progress", is_flag=True, help="Disable progress display")
@click.option("--fresh", is_flag=True, help="Force a full restart without resume")
def start(feature_or_description: str, no_progress: bool, fresh: bool):
    """Starts a Ralphy workflow for a feature.

    FEATURE_OR_DESCRIPTION: Either a feature name (ex: user-authentication) or a
    feature description in quotes (ex: "implement auth with devise")

    Normal mode (feature name):
        The PRD.md must exist in docs/features/<feature-name>/PRD.md

    Quick start mode (description):
        If the input doesn't match an existing feature with PRD.md, Ralphy will:
        - Derive a feature name from the description
        - Create the feature directory
        - Generate a minimal PRD.md
        - Run the full workflow

    By default, if the workflow was interrupted, it will resume from the
    last completed phase. Use --fresh to force a complete restart.
    """
    project = Path.cwd()
    logger = get_logger()
    show_progress = not no_progress

    # Check required dependencies
    missing_deps = _check_dependencies()
    if missing_deps:
        for name, hint in missing_deps:
            logger.error(f"{name} not found. Install it: {hint}")
        sys.exit(1)

    # Determine if this is quick start mode or normal mode
    is_quick_start = False
    feature_name = feature_or_description

    if FEATURE_NAME_PATTERN.match(feature_or_description):
        # Looks like a valid feature name - check if PRD exists
        feature_dir = get_feature_dir(project, feature_or_description)
        if not (feature_dir / "PRD.md").exists():
            # No PRD exists, treat as quick start
            is_quick_start = True
    else:
        # Not a valid feature name pattern, treat as description (quick start)
        is_quick_start = True

    if is_quick_start:
        # Quick start mode: derive feature name from description
        try:
            feature_name = description_to_feature_name(feature_or_description)
        except ValueError as e:
            logger.error(str(e))
            sys.exit(1)

        feature_dir = get_feature_dir(project, feature_name)
        prd_path = feature_dir / "PRD.md"

        # Check if the derived feature name conflicts with an existing feature
        if prd_path.exists():
            logger.warn(f"Feature '{feature_name}' already exists with a PRD.md")
            logger.info("Using existing PRD.md instead of generating a new one")
        else:
            # Create feature directory and generate PRD
            feature_dir.mkdir(parents=True, exist_ok=True)
            prd_content = generate_quick_prd(feature_or_description)
            prd_path.write_text(prd_content, encoding="utf-8")
            logger.info(f"Quick start: created {prd_path}")
    else:
        # Normal mode: feature name with existing PRD
        feature_dir = get_feature_dir(project, feature_name)
        prd_path = feature_dir / "PRD.md"
        if not prd_path.exists():
            logger.error(f"PRD.md not found in {feature_dir}")
            logger.error(f"Create {prd_path} with your feature requirements")
            sys.exit(1)

    # Vérifie si un workflow est déjà en cours
    state_manager = StateManager(project, feature_name)
    if state_manager.is_running():
        logger.warn(f"Un workflow est déjà en cours (phase: {state_manager.state.phase.value})")
        if not click.confirm("Voulez-vous le réinitialiser ?", default=False):
            sys.exit(0)
        state_manager.reset()

    # Lance l'orchestrateur
    logger.info(f"Démarrage du workflow pour: {feature_name}")
    logger.newline()

    orchestrator = Orchestrator(project, feature_name=feature_name, show_progress=show_progress)
    success = orchestrator.run(fresh=fresh)

    sys.exit(0 if success else 1)


@main.command()
@click.argument("feature_name", type=str, required=False)
@click.option("--all", "show_all", is_flag=True, help="Affiche le statut de toutes les features")
def status(feature_name: str = None, show_all: bool = False):
    """Affiche le statut du workflow.

    FEATURE_NAME: Nom de la feature (requis sauf si --all)
    """
    project = Path.cwd()
    logger = get_logger()

    if show_all:
        # Show status for all features
        features_dir = project / "docs" / "features"
        if not features_dir.exists():
            console.print("[yellow]No features found.[/yellow]")
            console.print(f"[dim]Create a feature with: mkdir -p docs/features/<feature-name> && touch docs/features/<feature-name>/PRD.md[/dim]")
            return

        features = [d.name for d in features_dir.iterdir() if d.is_dir()]
        if not features:
            console.print("[yellow]No features found.[/yellow]")
            return

        table = Table(title="Ralphy Features Status")
        table.add_column("Feature", style="cyan")
        table.add_column("Phase", style="green")
        table.add_column("Progress", style="blue")
        table.add_column("Last Completed", style="dim")

        for fname in sorted(features):
            state_manager = StateManager(project, fname)
            state = state_manager.state

            phase_style = "green"
            if state.phase in (Phase.FAILED, Phase.REJECTED):
                phase_style = "red"
            elif state.phase in (Phase.AWAITING_SPEC_VALIDATION, Phase.AWAITING_QA_VALIDATION):
                phase_style = "yellow"

            progress = f"{state.tasks_completed}/{state.tasks_total}" if state.tasks_total > 0 else "-"
            last_completed = state.last_completed_phase or "-"

            table.add_row(
                fname,
                f"[{phase_style}]{state.phase.value}[/{phase_style}]",
                progress,
                last_completed,
            )

        console.print(table)
        return

    # Single feature status
    if not feature_name:
        logger.error("Feature name required. Use --all to show all features.")
        sys.exit(1)

    # Validate feature name
    if not FEATURE_NAME_PATTERN.match(feature_name):
        logger.error(f"Invalid feature name: {feature_name}")
        sys.exit(1)

    state_manager = StateManager(project, feature_name)
    state = state_manager.state

    table = Table(title=f"Statut Ralphy - {feature_name}")
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
                f"[dim]💡 Pour reprendre le workflow: [cyan]ralphy start {feature_name}[/cyan][/dim]"
            )
            console.print(
                f"[dim]💡 Pour redémarrer de zéro: [cyan]ralphy start {feature_name} --fresh[/cyan][/dim]"
            )
        else:
            console.print(
                f"[dim]💡 Pour relancer le workflow: [cyan]ralphy start {feature_name}[/cyan][/dim]"
            )


@main.command()
@click.argument("feature_name", type=str)
def abort(feature_name: str):
    """Abort le workflow en cours.

    FEATURE_NAME: Nom de la feature
    """
    project = Path.cwd()
    logger = get_logger()

    # Validate feature name
    if not FEATURE_NAME_PATTERN.match(feature_name):
        logger.error(f"Invalid feature name: {feature_name}")
        sys.exit(1)

    state_manager = StateManager(project, feature_name)

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
@click.argument("feature_name", type=str)
def reset(feature_name: str):
    """Réinitialise l'état du workflow.

    FEATURE_NAME: Nom de la feature
    """
    project = Path.cwd()
    logger = get_logger()

    # Validate feature name
    if not FEATURE_NAME_PATTERN.match(feature_name):
        logger.error(f"Invalid feature name: {feature_name}")
        sys.exit(1)

    state_manager = StateManager(project, feature_name)

    if click.confirm(f"Réinitialiser l'état du workflow pour {feature_name} ?", default=False):
        state_manager.reset()
        logger.info("État réinitialisé")


@main.command("init-agents")
@click.argument("project_path", type=click.Path(exists=True, file_okay=False, resolve_path=True), required=False)
@click.option("--force", is_flag=True, help="Overwrite existing agent files")
def init_agents(project_path: str = None, force: bool = False):
    """Initialize custom agent templates.

    Copies default agent templates to .claude/agents/ in the project.
    These templates can be modified to adapt Ralphy to your tech stack.

    PROJECT_PATH: Path to the project (default: current directory)

    Use --force to overwrite existing agent files.
    """
    project = Path(project_path) if project_path else Path.cwd()
    logger = get_logger()

    # Create .claude/agents/ directory if it doesn't exist
    agents_dir = project / ".claude" / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)

    copied = 0
    skipped = 0

    for agent_file in AGENT_FILES:
        dest_path = agents_dir / agent_file

        # Skip if file exists and --force not specified
        if dest_path.exists() and not force:
            logger.warn(f"Skipping {agent_file} (exists, use --force to overwrite)")
            skipped += 1
            continue

        # Load content from package
        try:
            content = resources.files("ralphy.templates.agents").joinpath(agent_file).read_text(encoding="utf-8")
        except (FileNotFoundError, TypeError):
            logger.error(f"Template {agent_file} not found in package")
            continue

        # Write the file (agents include their own documentation in frontmatter)
        dest_path.write_text(content, encoding="utf-8")
        logger.info(f"Created {agent_file}")
        copied += 1

    # Summary
    console.print()
    if copied > 0:
        console.print(f"[green]✓[/green] {copied} agent(s) copied to {agents_dir}")
    if skipped > 0:
        console.print(f"[yellow]![/yellow] {skipped} agent(s) skipped (use --force to overwrite)")

    if copied > 0:
        console.print()
        console.print("[dim]Edit these files to customize Ralphy for your project.[/dim]")
        console.print("[dim]Remember: agents must contain EXIT_SIGNAL instruction.[/dim]")


@main.command("init-config")
@click.argument("project_path", type=click.Path(exists=True, file_okay=False, resolve_path=True), required=False)
@click.option("--force", is_flag=True, help="Overwrite existing config file")
def init_config(project_path: str = None, force: bool = False):
    """Initialize a default configuration file.

    Creates a .ralphy/config.yaml file with all default values and documentation
    comments. This file can be customized to adjust timeouts, models, and other
    settings for your project.

    PROJECT_PATH: Path to the project (default: current directory)

    Use --force to overwrite an existing config file.
    """
    project = Path(project_path) if project_path else Path.cwd()
    logger = get_logger()

    # Create .ralphy/ directory if it doesn't exist
    ralphy_dir = project / ".ralphy"
    ralphy_dir.mkdir(parents=True, exist_ok=True)

    config_path = ralphy_dir / "config.yaml"

    # Check if config already exists
    if config_path.exists() and not force:
        logger.warn(f"Config file already exists: {config_path}")
        console.print("[dim]Use --force to overwrite.[/dim]")
        return

    # Generate and write config template
    template = generate_config_template()
    config_path.write_text(template, encoding="utf-8")

    if config_path.exists():
        console.print(f"[green]✓[/green] Created {config_path}")
        console.print()
        console.print("[dim]Edit this file to customize Ralphy for your project.[/dim]")
        console.print("[dim]Only override values you need to change.[/dim]")
    else:
        logger.error(f"Failed to create config file: {config_path}")


if __name__ == "__main__":
    main()
