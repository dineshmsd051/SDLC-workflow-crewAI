"""
Custom CrewAI tools for the Multi-Agent SDLC Pipeline.

Provides:
  * JiraFetchTool          - fetch Jira issue details
  * ListFilesTool          - list files in the workspace
  * ReadFileTool           - read file contents
  * WriteFileTool          - create or modify a file
  * GitBranchTool          - create/checkout a local git branch
  * GitCommitPushTool      - stage, commit, and push changes
  * GitHubPullRequestTool  - open a PR against main on GitHub
"""

from __future__ import annotations

import base64
import fnmatch
import logging
import os
from pathlib import Path
from typing import List, Optional, Type

import requests
from crewai.tools import BaseTool
from git import GitCommandError, Repo
from github import Github, GithubException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DEFAULT_IGNORE = {
    ".git", ".venv", "venv", "__pycache__", "node_modules",
    ".pytest_cache", ".mypy_cache", ".idea", ".vscode", "dist", "build", ".eggs",
}


def _workspace_root() -> Path:
    root = os.getenv("WORKSPACE_PATH", os.getcwd())
    p = Path(root).expanduser().resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p


def _safe_path(rel_path: str) -> Path:
    """Resolve a path inside the workspace and prevent traversal."""
    root = _workspace_root()
    candidate = (root / rel_path).resolve()
    if root not in candidate.parents and candidate != root:
        raise ValueError(f"Path '{rel_path}' is outside workspace '{root}'.")
    return candidate


# ---------------------------------------------------------------------------
# Jira Tool
# ---------------------------------------------------------------------------

class JiraFetchInput(BaseModel):
    ticket_id: str = Field(..., description="Jira ticket key, e.g. PROJ-123")


class JiraFetchTool(BaseTool):
    name: str = "fetch_jira_ticket"
    description: str = (
        "Fetches a Jira ticket's summary, description, status, issue type, "
        "and acceptance criteria. Input: ticket_id (e.g. 'PROJ-123')."
    )
    args_schema: Type[BaseModel] = JiraFetchInput

    def _run(self, ticket_id: str) -> str:
        url = os.getenv("JIRA_URL")
        email = os.getenv("JIRA_EMAIL")
        token = os.getenv("JIRA_API_TOKEN")

        if not all([url, email, token]):
            return "ERROR: Missing JIRA_URL, JIRA_EMAIL or JIRA_API_TOKEN env vars."

        endpoint = f"{url.rstrip('/')}/rest/api/3/issue/{ticket_id}"
        try:
            resp = requests.get(
                endpoint,
                auth=(email, token),
                headers={"Accept": "application/json"},
                timeout=30,
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            logger.exception("Jira fetch failed")
            return f"ERROR: Jira request failed: {exc}"

        data = resp.json()
        fields = data.get("fields", {})

        # Description in the new ADF format
        description_raw = fields.get("description")
        description_text = self._adf_to_text(description_raw) if isinstance(description_raw, dict) else (description_raw or "")

        report = (
            f"# Jira Ticket: {data.get('key', ticket_id)}\n\n"
            f"**Summary:** {fields.get('summary', 'N/A')}\n\n"
            f"**Status:** {fields.get('status', {}).get('name', 'N/A')}\n\n"
            f"**Issue Type:** {fields.get('issuetype', {}).get('name', 'N/A')}\n\n"
            f"**Reporter:** {fields.get('reporter', {}).get('displayName', 'N/A')}\n\n"
            f"**Priority:** {fields.get('priority', {}).get('name', 'N/A')}\n\n"
            f"## Description\n\n{description_text or 'No description provided.'}\n"
        )
        return report

    @staticmethod
    def _adf_to_text(adf: dict) -> str:
        """Flatten Atlassian Document Format to plain text."""
        out: List[str] = []

        def walk(node):
            if not isinstance(node, dict):
                return
            ntype = node.get("type")
            if ntype == "text":
                out.append(node.get("text", ""))
            for child in node.get("content", []) or []:
                walk(child)
            if ntype in {"paragraph", "heading", "listItem"}:
                out.append("\n")

        walk(adf)
        return "".join(out).strip()


# ---------------------------------------------------------------------------
# Codebase Tools
# ---------------------------------------------------------------------------

class ListFilesInput(BaseModel):
    pattern: Optional[str] = Field(
        default=None,
        description="Optional glob pattern, e.g. '*.py'. If omitted, lists all files.",
    )


class ListFilesTool(BaseTool):
    name: str = "list_workspace_files"
    description: str = (
        "Recursively list files in the workspace. Optional 'pattern' filters by glob (e.g. '*.py'). "
        "Returns relative paths."
    )
    args_schema: Type[BaseModel] = ListFilesInput

    def _run(self, pattern: Optional[str] = None) -> str:
        root = _workspace_root()
        results: List[str] = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in DEFAULT_IGNORE]
            for fname in filenames:
                full = Path(dirpath) / fname
                rel = full.relative_to(root).as_posix()
                if pattern and not fnmatch.fnmatch(rel, pattern):
                    continue
                results.append(rel)

        if not results:
            return "No files found."
        return "\n".join(sorted(results))


class ReadFileInput(BaseModel):
    file_path: str = Field(..., description="Relative path of the file inside the workspace.")


class ReadFileTool(BaseTool):
    name: str = "read_file"
    description: str = "Reads the full content of a file given its workspace-relative path."
    args_schema: Type[BaseModel] = ReadFileInput

    def _run(self, file_path: str) -> str:
        try:
            path = _safe_path(file_path)
        except ValueError as exc:
            return f"ERROR: {exc}"

        if not path.exists():
            return f"ERROR: File '{file_path}' does not exist."
        if not path.is_file():
            return f"ERROR: '{file_path}' is not a file."

        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return f"ERROR: '{file_path}' is not a UTF-8 text file."
        except OSError as exc:
            return f"ERROR: Could not read '{file_path}': {exc}"

        return f"--- {file_path} ---\n{content}"


class WriteFileInput(BaseModel):
    file_path: str = Field(..., description="Relative path of the file inside the workspace.")
    content: str = Field(..., description="Full content to write. Overwrites the existing file.")


class WriteFileTool(BaseTool):
    name: str = "write_file"
    description: str = (
        "Creates or overwrites a file at the given workspace-relative path with the supplied content. "
        "Parent directories are auto-created."
    )
    args_schema: Type[BaseModel] = WriteFileInput

    def _run(self, file_path: str, content: str) -> str:
        try:
            path = _safe_path(file_path)
        except ValueError as exc:
            return f"ERROR: {exc}"

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        except OSError as exc:
            return f"ERROR: Could not write '{file_path}': {exc}"

        logger.info("Wrote file: %s (%d bytes)", file_path, len(content))
        return f"SUCCESS: Wrote {len(content)} bytes to '{file_path}'."


# ---------------------------------------------------------------------------
# Git / GitHub Tools
# ---------------------------------------------------------------------------

def _get_repo() -> Repo:
    return Repo(_workspace_root(), search_parent_directories=True)


class GitBranchInput(BaseModel):
    branch_name: str = Field(..., description="Branch name to create or checkout, e.g. feature/PROJ-123")


class GitBranchTool(BaseTool):
    name: str = "git_create_branch"
    description: str = (
        "Creates a new local git branch (or checks it out if it already exists) "
        "from the current HEAD. Input: branch_name."
    )
    args_schema: Type[BaseModel] = GitBranchInput

    def _run(self, branch_name: str) -> str:
        try:
            repo = _get_repo()
        except Exception as exc:
            return f"ERROR: Not a git repository: {exc}"

        try:
            if branch_name in [h.name for h in repo.heads]:
                repo.git.checkout(branch_name)
                return f"SUCCESS: Checked out existing branch '{branch_name}'."
            repo.git.checkout("-b", branch_name)
            return f"SUCCESS: Created and checked out branch '{branch_name}'."
        except GitCommandError as exc:
            return f"ERROR: Git branch operation failed: {exc}"


class GitCommitPushInput(BaseModel):
    commit_message: str = Field(..., description="Commit message.")
    remote: str = Field(default="origin", description="Remote name (default: origin).")


class GitCommitPushTool(BaseTool):
    name: str = "git_commit_and_push"
    description: str = (
        "Stages all changes, commits with the supplied message, and pushes the current "
        "branch to the configured remote (default 'origin'). Returns the commit SHA."
    )
    args_schema: Type[BaseModel] = GitCommitPushInput

    def _run(self, commit_message: str, remote: str = "origin") -> str:
        try:
            repo = _get_repo()
        except Exception as exc:
            return f"ERROR: Not a git repository: {exc}"

        try:
            repo.git.add(A=True)

            if not repo.is_dirty(untracked_files=True) and not repo.index.diff("HEAD"):
                logger.info("No changes to commit.")
                commit_sha = repo.head.commit.hexsha
            else:
                commit = repo.index.commit(commit_message)
                commit_sha = commit.hexsha
                logger.info("Created commit %s", commit_sha)

            current_branch = repo.active_branch.name

            if remote not in [r.name for r in repo.remotes]:
                return f"ERROR: Remote '{remote}' is not configured."

            origin = repo.remote(name=remote)
            push_info = origin.push(refspec=f"{current_branch}:{current_branch}", set_upstream=True)
            push_summary = "; ".join(str(p.summary).strip() for p in push_info)

            return (
                f"SUCCESS: Committed {commit_sha} on '{current_branch}' and pushed to {remote}. "
                f"Push summary: {push_summary}"
            )
        except GitCommandError as exc:
            return f"ERROR: Git commit/push failed: {exc}"


class GitHubPRInput(BaseModel):
    branch_name: str = Field(..., description="Source branch (head) for the PR.")
    title: str = Field(..., description="Pull request title.")
    body: str = Field(..., description="Pull request body / description (markdown allowed).")
    base_branch: str = Field(default="main", description="Target base branch (default: main).")


class GitHubPullRequestTool(BaseTool):
    name: str = "github_open_pull_request"
    description: str = (
        "Opens a Pull Request on GitHub from the given branch into the base branch. "
        "Reads GITHUB_TOKEN and GITHUB_REPOSITORY (owner/repo) from env. Returns the PR URL."
    )
    args_schema: Type[BaseModel] = GitHubPRInput

    def _run(self, branch_name: str, title: str, body: str, base_branch: str = "main") -> str:
        token = os.getenv("GITHUB_TOKEN")
        repo_full = os.getenv("GITHUB_REPOSITORY")  # "owner/name"

        if not token:
            return "ERROR: GITHUB_TOKEN env var is not set."

        # Auto-derive owner/repo from local origin if env not supplied
        if not repo_full:
            try:
                repo = _get_repo()
                origin_url = repo.remote("origin").url
                repo_full = self._parse_repo_from_url(origin_url)
            except Exception as exc:
                return f"ERROR: GITHUB_REPOSITORY not set and origin URL parsing failed: {exc}"

        try:
            gh = Github(token)
            gh_repo = gh.get_repo(repo_full)

            # If a PR already exists from this branch, return it.
            existing = gh_repo.get_pulls(state="open", head=f"{gh_repo.owner.login}:{branch_name}")
            for pr in existing:
                return f"SUCCESS: PR already exists -> {pr.html_url}"

            pr = gh_repo.create_pull(title=title, body=body, head=branch_name, base=base_branch)
            return f"SUCCESS: PR created -> {pr.html_url}"
        except GithubException as exc:
            return f"ERROR: GitHub API error: {exc.data if hasattr(exc, 'data') else exc}"
        except Exception as exc:
            return f"ERROR: Unexpected GitHub error: {exc}"

    @staticmethod
    def _parse_repo_from_url(url: str) -> str:
        # Supports https://github.com/owner/repo(.git) and git@github.com:owner/repo(.git)
        cleaned = url.strip()
        if cleaned.endswith(".git"):
            cleaned = cleaned[:-4]
        if cleaned.startswith("git@"):
            _, _, path = cleaned.partition(":")
            return path
        if "github.com/" in cleaned:
            return cleaned.split("github.com/", 1)[1]
        raise ValueError(f"Cannot parse GitHub repo from URL: {url}")


# ---------------------------------------------------------------------------
# Tool factories (used by the Crew)
# ---------------------------------------------------------------------------

def jira_tools() -> List[BaseTool]:
    return [JiraFetchTool()]


def codebase_tools() -> List[BaseTool]:
    return [ListFilesTool(), ReadFileTool(), WriteFileTool()]


def git_tools() -> List[BaseTool]:
    return [GitBranchTool(), GitCommitPushTool(), GitHubPullRequestTool()]