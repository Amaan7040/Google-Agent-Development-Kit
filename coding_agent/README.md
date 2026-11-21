# `coding_agent` — Autonomous MCP Coding & Safe-Shell Agent

`coding_agent` is a Google Agent Development Kit (ADK) agent designed to build, test, debug, run, and publish small Python web applications inside an isolated local workspace. It combines **Filesystem**, **Safe-Shell**, and **GitHub** Model Context Protocol (MCP) toolsets with strict security guardrails and Human-in-the-Loop (HITL) approval controls.

---

## Project Structure

```text
coding_agent/
├── __init__.py              # Exports agent module for ADK loader
├── agent.py                 # Main ADK Agent definition, MCP connections & HITL rules
├── .env                     # Environment variables (API keys, GitHub PAT, workspace path)
├── servers/
│   └── shell_server.py      # Custom FastMCP / MCPServer for safe command & server execution
└── workspace/               # Default isolated directory where all generated code lives
```

---

## Architecture & MCP Toolsets

`coding_agent` connects to three distinct MCP toolsets:

### 1. Local Filesystem MCP (`@modelcontextprotocol/server-filesystem`)
* **Transport:** `stdio` via `npx`
* **Scope:** Restricted strictly to the resolved `WORKSPACE` directory.
* **Enabled Tools:** `list_directory`, `directory_tree`, `read_text_file`, `read_multiple_files`, `search_files`, `get_file_info`, `create_directory`, `write_file`, `edit_file`.

### 2. Safe-Shell MCP Server (`servers/shell_server.py`)
* **Transport:** `stdio` using the active Python interpreter (`sys.executable`) so commands automatically run inside the project's virtual environment.
* **Enabled Tools:** `run_command`, `workspace_info`, `start_server`, `stop_server`, `server_logs`, `check_url`.

### 3. GitHub MCP (`https://api.githubcopilot.com/mcp/`)
* **Transport:** Streamable HTTP (loaded automatically when `GITHUB_PAT` is present in `.env`).
* **Read Tools (Auto-Approved):** `get_me`, `get_file_contents`, `list_branches`, `list_issues`, `issue_read`, `list_pull_requests`.
* **Write Tools (Approval Required):** `create_repository`, `create_branch`, `push_files`, `create_pull_request`, `add_issue_comment`.

---

## Safe-Shell Server (`servers/shell_server.py`) Deep Dive

Because standard shell access can be risky for autonomous agents, `shell_server.py` enforces strict execution boundaries:

### Security Guardrails
* **Allowlisted Programs Only:** Only `python`, `pytest`, `pip`, and `git` can be executed. File-reading commands (`cat`, `ls`, etc.) are intentionally excluded so file access stays cleanly within the Filesystem MCP server.
* **Blocked Sub-Commands:**
  * `git`: `push`, `remote`, `config`, `reset`, `clean`, `rebase` are blocked. (Remote publishing is handled via GitHub MCP `push_files`.)
  * `pip`: `uninstall`, `download` are blocked.
* **No Shell Injection or Chaining:** Commands are parsed with `shlex.split` and executed with `shell=False`. Pipes (`|`), redirects (`>`, `<`), and command chaining (`&&`, `;`, `||`) are rejected.
* **Resource Caps:** Command execution is capped at **60 seconds** (`DEFAULT_TIMEOUT_SECONDS`), and tool output is truncated at **4,000 characters** (`MAX_OUTPUT_CHARS`) to keep model context clean.

### Human-in-the-Loop (HITL) Approval Policy
Defined in `agent.py` via `shell_needs_confirmation`:
* **Auto-Approved (Runs Immediately):** Read-only checks and tests starting with `pytest`, `python -m pytest`, `git status`, `git diff`, or `git log`.
* **Requires Manual Approval:** State-changing commands (`pip install`, `git init`, `git add`, `git commit`) and starting live servers (`start_server`).

### Background Web Server Management (Port `8001`)
Since `adk web` occupies port `8000`, `shell_server.py` manages live ASGI applications (such as FastAPI/Uvicorn) on **`http://127.0.0.1:8001`**:
* **`start_server(module)`**: Launches `uvicorn <module> --host 127.0.0.1 --port 8001` in the background (e.g., `"app:app"`). Logs are written to the OS temp directory (`safe-shell-server.log`) outside the workspace so logs never pollute Git commits.
* **`check_url(path)`**: Sends local HTTP GET requests to `http://127.0.0.1:8001<path>` to verify endpoints.
* **`server_logs()`**: Displays whether the server is running along with recent stdout/stderr logs.
* **`stop_server()`**: Gracefully terminates the background server (also triggered automatically on agent shutdown via `atexit`).

---

## Setup & Prerequisites

### 1. System Requirements
* **Python 3.10+** (with virtual environment activated)
* **Node.js & `npx`** (required to run `@modelcontextprotocol/server-filesystem`)
* **Git** configured locally with `user.name` and `user.email` (since `git config` is blocked inside `shell_server.py`)

### 2. Install Dependencies
```bash
pip install google-adk mcp python-dotenv fastapi uvicorn pytest httpx
```

### 3. Configure `.env`
Create a `.env` file inside the `coding_agent/` directory:
```env
GOOGLE_API_KEY=your_gemini_api_key_here
GITHUB_PAT=your_github_personal_access_token_here
# Optional: override default ./workspace path
# WORKSPACE_DIR=C:/path/to/custom/workspace
```

---

## Running the Agent

1. Open your terminal in the **parent directory** containing the `coding_agent/` folder and start the ADK Web UI:
   ```bash
   adk web
   ```
2. Open **`http://127.0.0.1:8000`** in your browser.
3. Select **`coding_agent`** from the top-left agent dropdown menu.
4. Send your project prompt and click **Approve** when prompted for state-changing shell or GitHub write actions.
5. Once the agent starts your web app, access it live at **`http://127.0.0.1:8001`**.

---

## Agent Workflow Rules

1. **Inspect First:** Always checks existing workspace files before writing code.
2. **Incremental Steps & Testing:** Builds in small steps and validates endpoints using `pytest` and FastAPI's `TestClient` before starting the live server.
3. **3-Strike Error Limit:** Stops and explains the root cause if the same test fails 3 consecutive times.
4. **Live Verification:** Uses `start_server` + `check_url` to verify the running application on port `8001` and leaves it running unless instructed to stop.