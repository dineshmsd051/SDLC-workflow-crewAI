# Multi-Agent SDLC Pipeline (CrewAI)

An autonomous, end-to-end Software Development Life Cycle pipeline powered by
[CrewAI](https://github.com/joaomdmoura/crewAI). Six specialized AI agents
collaborate to take a Jira ticket from requirements to a Pull Request on GitHub.

## 🧠 Pipeline Stages

| # | Agent             | Responsibility                                        |
|---|-------------------|--------------------------------------------------------|
| 1 | `jira_analyst`    | Fetches the Jira ticket and writes a tech spec        |
| 2 | `code_architect`  | Scans the codebase and produces an implementation plan|
| 3 | `developer`       | Writes the production code to disk                    |
| 4 | `test_engineer`   | Authors pytest unit tests                             |
| 5 | `code_reviewer`   | Performs a rigorous code review                       |
| 6 | `devops_manager`  | Branches, commits, pushes, and opens a GitHub PR      |

## 📁 Project Structure

```
.
├── agents/
│   ├── config/
│   │   ├── agents.yaml
│   │   └── tasks.yaml
│   ├── tools/
│   │   └── custom_tools.py
│   ├── crew.py
│   └── main.py
├── requirements.txt
└── README.md
```

## 🔧 Setup

### 1. Clone the target codebase
The pipeline operates on a local git repository. The repository **must**:
- be a valid git repo (`git init` already run)
- have an `origin` remote pointing to GitHub
- have a `main` branch on the remote

### 2. Install dependencies

```bash
python -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Configure environment variables

Create a `.env` file in the project root:

```bash
# Jira
JIRA_URL=https://yourorg.atlassian.net
[email protected]
JIRA_API_TOKEN=your_jira_api_token

# GitHub
GITHUB_TOKEN=ghp_your_personal_access_token
GITHUB_REPOSITORY=your-org/your-repo   # optional, auto-detected from origin

# Workspace (the local codebase to modify)
WORKSPACE_PATH=/absolute/path/to/your/repo

# LLM Provider — pick one
OPENAI_API_KEY=sk-...
OPENAI_MODEL_NAME=gpt-4o-mini
# or
# ANTHROPIC_API_KEY=...
```

#### How to get the tokens
- **Jira API token:** https://id.atlassian.com/manage-profile/security/api-tokens
- **GitHub PAT:** https://github.com/settings/tokens (needs `repo` scope; for fine-grained tokens, grant Contents: read/write and Pull requests: read/write)

## 🚀 Usage

```bash
# Run against a Jira ticket
python -m agents.main PROJ-123

# Or with explicit options
python -m agents.main --ticket PROJ-123 --workspace /path/to/repo
```

The pipeline will:
1. Fetch ticket `PROJ-123` from Jira.
2. Analyze your local codebase at `WORKSPACE_PATH`.
3. Write source files and tests to disk.
4. Create branch `feature/PROJ-123`.
5. Commit, push, and open a PR against `main`.

The PR URL is printed at the end.

## ⚙️ How Tools Map to Agents

| Tool                       | Used By                              |
|----------------------------|--------------------------------------|
| `fetch_jira_ticket`        | `jira_analyst`                       |
| `list_workspace_files`     | architect, developer, tester, reviewer, devops |
| `read_file`                | architect, developer, tester, reviewer, devops |
| `write_file`               | developer, test_engineer             |
| `git_create_branch`        | `devops_manager`                     |
| `git_commit_and_push`      | `devops_manager`                     |
| `github_open_pull_request` | `devops_manager`                     |

## 🛡️ Safety Notes

- File operations are sandboxed to `WORKSPACE_PATH` — path traversal is blocked.
- The DevOps agent **never** pushes directly to `main`; it always opens a PR.
- All tools return descriptive `ERROR:` prefixed strings on failure so the
  agent loop can self-correct rather than crashing the pipeline.

## 🧪 Local Development

```bash
# Lint & type-check (recommended)
pip install ruff mypy
ruff check agents/
mypy agents/
```

## 🐛 Troubleshooting

| Symptom                                  | Fix                                                        |
|------------------------------------------|------------------------------------------------------------|
| `ERROR: Not a git repository`            | Run `git init` and add an origin remote in `WORKSPACE_PATH`|
| `Remote 'origin' is not configured`      | `git remote add origin git@github.com:owner/repo.git`      |
| `GitHub API error: 422 ... no commits`   | Push at least one commit to `main` before running          |
| `Missing required environment variables` | Populate `.env` per the Setup section                      |
| Agents loop without writing files        | Increase model capability (`OPENAI_MODEL_NAME=gpt-4o`)     |

## 📜 License

MIT — use, fork, and adapt freely.