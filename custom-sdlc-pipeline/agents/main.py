"""
Entry point CLI for the Multi-Agent SDLC pipeline.

Usage:
    python -m agents.main --ticket PROJ-123
    python -m agents.main PROJ-123
"""

from __future__ import annotations

import os
import sys
from typing import List, Tuple

import click
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel

from agents.crew import SDLCCrew

console = Console()

REQUIRED_ENV_VARS: List[Tuple[str, str]] = [
    ("JIRA_URL", "Base URL of your Jira instance, e.g. https://yourorg.atlassian.net"),
    ("JIRA_EMAIL", "Atlassian account email"),
    ("JIRA_API_TOKEN", "Jira API token"),
    ("GITHUB_TOKEN", "GitHub personal access token with repo scope"),
]

OPTIONAL_ENV_VARS: List[Tuple[str, str]] = [
    ("GITHUB_REPOSITORY", "owner/repo (auto-detected from local origin if omitted)"),
    ("WORKSPACE_PATH", "Path to the target codebase (defaults to CWD)"),
    ("OPENAI_API_KEY", "OpenAI key (or use ANTHROPIC_API_KEY)"),
    ("ANTHROPIC_API_KEY", "Anthropic key (alternative to OPENAI_API_KEY)"),
    ("OPENAI_MODEL_NAME", "LLM model name (default: gpt-4o-mini)"),
]


def _check_environment() -> None:
    missing = [name for name, _ in REQUIRED_ENV_VARS if not os.getenv(name)]
    if missing:
        console.print(
            Panel.fit(
                f"[bold red]Missing required environment variables:[/]\n  - " + "\n  - ".join(missing),
                title="Configuration Error",
                border_style="red",
            )
        )
        sys.exit(1)

    if not os.getenv("OPENAI_API_KEY") and not os.getenv("ANTHROPIC_API_KEY"):
        console.print(
            Panel.fit(
                "[bold red]Either OPENAI_API_KEY or ANTHROPIC_API_KEY must be set.[/]",
                title="LLM Provider Missing",
                border_style="red",
            )
        )
        sys.exit(1)


@click.command(context_settings=dict(help_option_names=["-h", "--help"]))
@click.argument("ticket", required=False)
@click.option("--ticket", "-t", "ticket_opt", help="Jira ticket ID, e.g. PROJ-123")
@click.option("--workspace", "-w", help="Override workspace path (sets WORKSPACE_PATH).")
def main(ticket: str, ticket_opt: str, workspace: str) -> None:
    """Run the Multi-Agent SDLC pipeline for a given Jira ticket."""
    load_dotenv()

    ticket_id = ticket or ticket_opt
    if not ticket_id:
        console.print("[bold red]Error:[/] Jira ticket ID is required.\n")
        console.print("Usage: python -m agents.main PROJ-123")
        sys.exit(2)

    if workspace:
        os.environ["WORKSPACE_PATH"] = workspace

    _check_environment()

    console.print(
        Panel.fit(
            f"[bold cyan]Starting SDLC pipeline[/]\n"
            f"Ticket:    [yellow]{ticket_id}[/]\n"
            f"Workspace: [yellow]{os.getenv('WORKSPACE_PATH', os.getcwd())}[/]\n"
            f"Model:     [yellow]{os.getenv('OPENAI_MODEL_NAME', 'gpt-4o-mini')}[/]",
            title="🤖 Multi-Agent SDLC",
            border_style="cyan",
        )
    )

    try:
        crew = SDLCCrew(jira_ticket_id=ticket_id)
        result = crew.kickoff()
    except Exception as exc:
        console.print(
            Panel.fit(
                f"[bold red]Pipeline failed:[/]\n{exc}",
                title="Execution Error",
                border_style="red",
            )
        )
        raise

    console.print(
        Panel.fit(
            f"[bold green]Pipeline completed successfully![/]\n\n{result}",
            title="✅ Done",
            border_style="green",
        )
    )


if __name__ == "__main__":
    main()