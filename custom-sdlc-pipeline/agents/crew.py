"""
CrewAI orchestration: wires agents and tasks for the SDLC pipeline.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

import yaml
from crewai import Agent, Crew, Process, Task

from agents.tools.custom_tools import (
    codebase_tools,
    git_tools,
    jira_tools,
)

CONFIG_DIR = Path(__file__).parent / "config"


def _load_yaml(filename: str) -> Dict[str, Any]:
    path = CONFIG_DIR / filename
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


class SDLCCrew:
    """Builds and runs the Multi-Agent SDLC Crew."""

    def __init__(self, jira_ticket_id: str) -> None:
        self.jira_ticket_id = jira_ticket_id
        self.agents_cfg = _load_yaml("agents.yaml")
        self.tasks_cfg = _load_yaml("tasks.yaml")

        # LLM model can be overridden via env var
        self.llm_model = os.getenv("OPENAI_MODEL_NAME", "gpt-4o-mini")

        self._agents: Dict[str, Agent] = {}
        self._tasks: Dict[str, Task] = {}

    # ------------------------------------------------------------------
    # Agent factory
    # ------------------------------------------------------------------
    def _build_agent(self, key: str, tools=None) -> Agent:
        cfg = self.agents_cfg[key]
        return Agent(
            role=cfg["role"],
            goal=cfg["goal"],
            backstory=cfg["backstory"],
            tools=tools or [],
            verbose=cfg.get("verbose", True),
            allow_delegation=cfg.get("allow_delegation", False),
            llm=self.llm_model,
        )

    def _build_agents(self) -> None:
        self._agents = {
            "jira_analyst": self._build_agent("jira_analyst", tools=jira_tools()),
            "code_architect": self._build_agent("code_architect", tools=codebase_tools()),
            "developer": self._build_agent("developer", tools=codebase_tools()),
            "test_engineer": self._build_agent("test_engineer", tools=codebase_tools()),
            "code_reviewer": self._build_agent("code_reviewer", tools=codebase_tools()),
            "devops_manager": self._build_agent(
                "devops_manager", tools=codebase_tools() + git_tools()
            ),
        }

    # ------------------------------------------------------------------
    # Task factory
    # ------------------------------------------------------------------
    def _build_tasks(self) -> None:
        format_vars = {"jira_ticket_id": self.jira_ticket_id}

        # First pass: create tasks without context
        for key, cfg in self.tasks_cfg.items():
            description = cfg["description"].format(**format_vars)
            expected_output = cfg["expected_output"].format(**format_vars)
            agent_key = cfg["agent"]
            self._tasks[key] = Task(
                description=description,
                expected_output=expected_output,
                agent=self._agents[agent_key],
            )

        # Second pass: wire context references
        for key, cfg in self.tasks_cfg.items():
            ctx_keys = cfg.get("context") or []
            if ctx_keys:
                self._tasks[key].context = [self._tasks[k] for k in ctx_keys]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def build(self) -> Crew:
        self._build_agents()
        self._build_tasks()

        # Preserve declaration order from tasks.yaml
        ordered_tasks = [self._tasks[k] for k in self.tasks_cfg.keys()]
        ordered_agents = list(self._agents.values())

        return Crew(
            agents=ordered_agents,
            tasks=ordered_tasks,
            process=Process.sequential,
            verbose=True,
        )

    def kickoff(self) -> Any:
        crew = self.build()
        inputs = {"jira_ticket_id": self.jira_ticket_id}
        return crew.kickoff(inputs=inputs)