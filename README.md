# MCP Integration with ChatGPT Web

A standalone **Model Context Protocol (MCP)** server that lets ChatGPT connect to registered local development repositories through a remote HTTPS endpoint. The server exposes repository, filesystem, search, code-intelligence, terminal, Git-inspection, and repository-analysis tools. Your files remain on your machine; the MCP server brokers approved tool requests into the selected repository.

> **Windows-first quick path:** configure the repository registry, double-click `start.bat`, copy the generated `/mcp` endpoint, and add it in ChatGPT using **Plugins → + → Add custom MCP server** (where that option is available for your account/workspace).

## Contents

- [Architecture](#architecture)
- [Requirements](#requirements)
- [First-time setup on Windows](#first-time-setup-on-windows)
- [Configure local repositories](#configure-local-repositories)
- [Start with the Windows launcher](#start-with-the-windows-launcher)
- [Add this MCP server to ChatGPT](#add-this-mcp-server-to-chatgpt)
- [Everyday start, status, and stop](#everyday-start-status-and-stop)
- [Run from PowerShell](#run-from-powershell)
- [Endpoints and transports](#endpoints-and-transports)
- [Tools exposed by this server](#tools-exposed-by-this-server)
- [Troubleshooting](#troubleshooting)
- [Security notes](#security-notes)
- [Tests](#tests)
- [Project layout](#project-layout)

---

## Architecture

```text
ChatGPT on the web
        |
        | HTTPS + MCP
        v
Public HTTPS tunnel (Cloudflare Quick Tunnel by default; optional configured tunnel)
        |
        v
MCP server on this machine (default 127.0.0.1:8766)
        |
        v
config/repositories.json  ---> registered local repositories
                                   |
                                   +-- interview-copilot
                                   +-- AI_jobs_apply
                                   +-- MCP
                                   +-- any other enabled repository
```

The server is a separate project from the repositories it manages. Add each local repository to `config/repositories.json`; the MCP server does not need to be copied into those projects. Tool operations act on the currently selected repository and are reflected on disk, so changes can appear immediately in VS Code.

## Requirements

For the documented one-click Windows setup:

- Windows 10/11.
- Python **3.10 or newer** on PATH.
- Git, if cloning the project.
- Internet connectivity for installing Python packages and running the HTTPS tunnel.
- Cloudflare Tunnel (`cloudflared`) available on PATH for the default Quick Tunnel mode. Install it from an elevated or normal PowerShell window if permitted:
  ```powershell
  winget install Cloudflare.cloudflared
  ```
- A ChatGPT account/workspace that permits adding custom MCP servers. Availability and permissions depend on plan and workspace configuration. See [OpenAI's custom MCP server connection guide](https://help.openai.com/en/articles/12584461-connecting-custom-mcp-servers-in-chatgpt).

A permanent Cloudflare named tunnel or ngrok configuration is optional. See the tunnel settings in `app/config.py` and the notes in [docs/CHATGPT_SETUP.md](docs/CHATGPT_SETUP.md).

## First-time setup on Windows

### 1. Download the repository

If you have not already cloned it, open PowerShell and run:

```powershell
git clone https://github.com/Jashuva-Billa/MCP-Integration-with-chatgptweb.git
cd MCP-Integration-with-chatgptweb
```

If you already have the repository locally, open PowerShell in the existing MCP folder instead. Do not clone a second copy just to start the server.

### 2. Create a Python virtual environment

Run the following from the MCP repository root:

```powershell
python -m venv venv
.\venv\Scripts\python.exe -m pip install --upgrade pip
.\venv\Scripts\python.exe -m pip install -r requirements.txt
```

The launcher checks for `venv\Scripts\python.exe` and uses it when present. You do not have to activate the virtual environment before double-clicking `start.bat`.

### 3. Check the environment

```powershell
.\venv\Scripts\python.exe scripts\doctor.py
```

The diagnostic checks the Python version, required packages, whether port `8766` is available, repository configuration, and tunnel executable. A warning that port 8766 is busy can mean the MCP server is already running; check it with `status_all.bat` or open `http://127.0.0.1:8766/health` in a browser before starting another copy.

### 4. Configure repositories

Open `config/repositories.json` in your editor. This file lists the local directories that the server can work with. Update it for your own machine, following [Configure local repositories](#configure-local-repositories) below.

> **Important:** paths in the registry are machine-specific. The sample registry currently includes local paths from the developer's Windows environment. Replace them with valid directories on your own machine before using the server.

### 5. Start the server

Continue to [Start with the Windows launcher](#start-with-the-windows-launcher).

## Configure local repositories

Edit `config/repositories.json`. Each key is the repository name that you can later pass to `select_repository`. Each repository entry has a local `path`, a human-readable `description`, and an `enabled` flag.

Example:

```json
{
  "repositories": {
    "my-python-app": {
      "path": "C:/Users/YourName/Development/my-python-app",
      "description": "My Python application",
      "enabled": true
    },
    "my-web-app": {
      "path": "C:/Users/YourName/Development/my-web-app",
      "description": "My web application",
      "enabled": true
    }
  }
}
```

Configuration tips:

- Use forward slashes in Windows JSON paths (for example, `C:/Users/YourName/Development/app`) or properly escaped backslashes.
- Each enabled path must exist and be accessible to your Windows account.
- Use unique repository names.
- Do not register a parent folder that contains unrelated or sensitive files. Register the specific project root instead.
- Keep `.env`, API keys, credentials, certificates, and other secrets out of the registry and repository files. Secret-file protection is built into several MCP file tools.
- The registry is local configuration; do not publish your real machine paths unnecessarily.

## Start with the Windows launcher

### 1. Double-click `start.bat`

In File Explorer, open the MCP repository folder and double-click **`start.bat`**.

The batch file performs these actions:

1. Changes the working directory to the MCP repository root.
2. Uses `venv\Scripts\python.exe` if it exists; otherwise it tries `python` from PATH.
3. Runs `scripts/doctor.py` to print environment diagnostics.
4. Runs `scripts/tunnel.py start`. The tunnel script starts the local MCP server if it is not already healthy, then launches the configured tunnel.
5. Reads the tunnel's public URL from `runtime/tunnel.url`.
6. Copies the Streamable HTTP endpoint (`https://.../mcp`) to the Windows clipboard when a public tunnel URL is available.
7. Displays a menu for opening ChatGPT, opening the VS Code workspace, running the connection test, copying endpoints, checking service status, stopping services, or closing the launcher while leaving the services running.

Keep the launcher window open while choosing menu options. Selecting **9** exits the menu but deliberately leaves the MCP server and tunnel running in the background.

### 2. Copy the endpoint

When startup succeeds, the menu shows endpoints similar to these:

```text
Streamable HTTP: https://<generated-host>.trycloudflare.com/mcp
SSE Endpoint:    https://<generated-host>.trycloudflare.com/sse
Local health:    http://127.0.0.1:8766/health
```

The host above is an example, not a real endpoint. Use the exact URL printed by your launcher.

- The Streamable HTTP URL is normally copied to the clipboard automatically.
- Choose menu option **5** to copy it again.
- Choose menu option **6** to copy the SSE endpoint if you need it.
- The public Quick Tunnel address can change when the tunnel restarts. If that happens, update the ChatGPT plugin connection to the new URL.

### 3. Use the launcher's menu

| Option | Action |
| --- | --- |
| `1` | Open ChatGPT in the default browser and show the endpoint to use. |
| `2` | Open `multi-repo.code-workspace` in VS Code if present; otherwise open the MCP folder. |
| `3` | Open this MCP folder in VS Code. |
| `4` | Run `scripts/test_connection.py` for connection diagnostics. |
| `5` | Copy the Streamable HTTP `/mcp` endpoint to the clipboard. |
| `6` | Copy the SSE `/sse` endpoint to the clipboard. |
| `7` | Run `status_all.bat` to inspect server/tunnel status. |
| `8` | Run `stop_all.bat` and exit. |
| `9` | Close the launcher but leave background services running. |

## Add this MCP server to ChatGPT

ChatGPT connects to a **remote HTTPS endpoint**; it cannot use `http://127.0.0.1:8766/mcp` from its cloud service as your local machine's server address. Start the tunnel first and provide the public HTTPS endpoint, or use a Secure MCP Tunnel option if one is available to your account.

The current documented ChatGPT web flow is described below. The exact labels may vary by product rollout, account, or workspace policy.

### Current Plugins flow

1. Start the MCP server and HTTPS tunnel using `start.bat`.
2. Copy the public **Streamable HTTP endpoint**, including the `/mcp` suffix. Example format: `https://<generated-host>.trycloudflare.com/mcp`.
3. Open [ChatGPT](https://chatgpt.com) in your browser.
4. Go to **Plugins**.
5. Select the **+** button and choose **Add custom MCP server**.
6. Enter a recognizable name, for example **Local Multi-Repo MCP**, and optionally a description such as *Tools for inspecting and editing my registered development repositories*.
7. Under **Connection**, paste the public HTTPS `/mcp` endpoint. If the UI offers a supported Secure MCP Tunnel choice and you intend to use it, follow the UI's tunnel flow instead.
8. Configure authentication to match the server. See the authentication section immediately below.
9. Read the risk warning and only continue if you trust this server and understand that its tools can read or modify files and run development commands within the configured boundaries. Tick the acknowledgement checkbox.
10. Choose **Create as a plugin**.
11. Review the discovered tools and descriptions. Verify that the tool list contains expected MCP operations before using it.

OpenAI reference: [Connecting custom MCP servers in ChatGPT](https://help.openai.com/en/articles/12584461-connecting-custom-mcp-servers-in-chatgpt).

### Authentication: make the UI match the server

This repository currently enables the Bearer authentication middleware when either `MCP_AUTH_ENABLED` is true **or** `MCP_AUTH_TOKEN` is non-empty. Configure authentication before exposing the server outside your machine.

- For a protected connection, set `MCP_AUTH_ENABLED=true` and a long, unique `MCP_AUTH_TOKEN` in a local `.env` file, and select the matching authentication method in ChatGPT.
- The token must match exactly between the server's `.env` and ChatGPT.
- Do not paste the token into Git, README files, screenshots, logs, or prompts.
- The project configuration has local-development defaults with authentication disabled if no token is configured. **Do not expose an unauthenticated server to the public internet.** Use an authenticated deployment or a supported secure tunnel suitable for your environment.
- The repository's settings class reads `.env` from the process working directory. Start the server through the supplied scripts from the repository root so configuration is loaded as expected.

If your account's connection form uses a different authentication model (for example, OAuth or a tunnel-managed connection), follow that form's requirements. Do not assume a Bearer-token field exists in every UI.

### Test the plugin

1. Once creation succeeds, start a **new ChatGPT conversation**.
2. Use the app/plugin selector in the composer or type `@` if the UI supports app mentions, then select the MCP plugin you created.
3. Begin with a read-only prompt:
   ```text
   List my configured repositories and tell me which repository is currently selected.
   Do not modify any files.
   ```
4. Test repository selection:
   ```text
   Select the repository named my-python-app. Show its Git status and list its top-level files.
   Do not change any files.
   ```
5. Only after read-only checks work should you test writes on a disposable test repository. Review write/terminal actions carefully and approve only actions you intend to perform.

The server-side tool list is registered in `app/main.py`; review it when verifying a connection or refreshing the plugin's available tools.

## Everyday start, status, and stop

After the first-time setup, the usual routine is:

1. Double-click `start.bat`.
2. Wait for the tunnel URL and menu to appear.
3. If the Quick Tunnel address has changed, update the plugin's endpoint in ChatGPT.
4. Use option **1** to open ChatGPT, or leave the menu available while you work.
5. When finished, choose option **8** or double-click `stop_all.bat`.

Other helper files:

- **`status_all.bat`** — reports the MCP server status and the stored public tunnel URL/endpoints.
- **`stop_all.bat`** — stops the tunnel and local MCP server.
- **`runtime/mcp_server.log`** — server log.
- **`runtime/cloudflared.log`** — tunnel log.
- **`runtime/tunnel.url`** — current public base URL written by the tunnel script.
- **`runtime/mcp_server.pid`** and **`runtime/cloudflared.pid`** — process ID files managed by the startup scripts.

Log files and runtime state can contain host or diagnostic information. Review them before sharing externally.

## Run from PowerShell

Use these commands from the MCP repository root if you prefer not to use the menu.

### Run diagnostics

```powershell
python scripts/doctor.py
```

### Start the local server only

```powershell
python scripts/start.py start
```

Local endpoint URLs:

- Health: `http://127.0.0.1:8766/health`
- Streamable HTTP: `http://127.0.0.1:8766/mcp`
- SSE: `http://127.0.0.1:8766/sse`

Starting only the local server is useful for local diagnostics or MCP clients that can reach your machine directly. It is not, by itself, a connection method for ChatGPT's hosted web service.

### Start the tunnel (also starts the server if needed)

```powershell
python scripts/tunnel.py start
```

### Check or stop

```powershell
python scripts/start.py status
python scripts/tunnel.py stop
python scripts/start.py stop
```

For a typical remote ChatGPT connection, prefer `start.bat` because it starts the server and tunnel in sequence and presents the endpoint/menu in one place.

## Endpoints and transports

| Purpose | Local address | Public address pattern |
| --- | --- | --- |
| Health check | `http://127.0.0.1:8766/health` | `https://<generated-host>/health` |
| Streamable HTTP (recommended for this setup) | `http://127.0.0.1:8766/mcp` | `https://<generated-host>/mcp` |
| SSE transport | `http://127.0.0.1:8766/sse` | `https://<generated-host>/sse` |

The server defaults to host `127.0.0.1`, port `8766`. These settings are defined in `app/config.py`. If you change the port or hosting configuration, update the scripts and documentation consistently.

## Tools exposed by this server

Tool names below are registered in `app/main.py`; the implementation is in `app/tools/`.

| Area | Tools |
| --- | --- |
| Workspace | `list_repositories`, `select_repository`, `get_current_repository`, `add_repository`, `remove_repository`, `inspect_workspace` |
| Filesystem | `list_files`, `read_file`, `write_file`, `create_directory`, `delete_file` |
| Search | `search_code` |
| Code intelligence | `find_symbol`, `find_references`, `list_functions`, `list_classes`, `get_file_structure` |
| Terminal | `run_command` |
| Git inspection | `git_status`, `git_diff`, `git_branch`, `git_log`, `git_show`, `git_changed_files` |
| Repository analysis | `analyze_repository` |

**Tool behavior:** `write_file` changes files on disk. `delete_file` deletes an individual file (directory deletion is rejected). `run_command` executes approved development commands with restrictions, a time limit, and output limits. The server is not read-only.

## Troubleshooting

### The launcher closes or reports Python is missing

- Install Python 3.10+ and ensure `python` works in PowerShell.
- Install dependencies using `venv\Scripts\python.exe -m pip install -r requirements.txt`.
- If a virtual environment exists, confirm `venv\Scripts\python.exe` exists inside this repository.

### The doctor says port 8766 is in use

- Check whether a server is already running by opening `http://127.0.0.1:8766/health`.
- Run `status_all.bat` to see whether the server's recorded PID is active.
- Avoid killing processes blindly; port 8766 might belong to a different program.

### Local health works but ChatGPT cannot connect

- Confirm that the public HTTPS URL is the current URL written in `runtime/tunnel.url` and printed by the launcher.
- Use the complete `/mcp` endpoint, not the base URL and not the local `127.0.0.1` URL.
- Confirm the tunnel process is running. Review `runtime/cloudflared.log`.
- Confirm the ChatGPT authentication configuration matches server configuration.
- Try the endpoint again after restarting the tunnel; an ephemeral Quick Tunnel URL changes on restart.
- Confirm your account and workspace permissions allow custom MCP server plugins. Review OpenAI's current documentation if the Plugins menu is unavailable.

### ChatGPT cannot see the tools or tool list is stale

- Ensure the endpoint ends with `/mcp`.
- Review `runtime/mcp_server.log` for startup or transport errors.
- Reopen the plugin configuration and use its refresh/rescan option if the interface provides one.
- Verify that the local server includes the expected registration in `app/main.py` and that the tool's module imports successfully.

### `cloudflared` is not detected

Install Cloudflare Tunnel with `winget install Cloudflare.cloudflared`, close and reopen the terminal, then run `where.exe cloudflared`. If it is installed in a non-standard location, use the supported configuration field `CLOUDFLARED_PATH` in your local environment settings.

### Where are the logs?

Check `runtime/mcp_server.log` for MCP server output and `runtime/cloudflared.log` for tunnel output. Do not share the logs publicly without checking for machine paths and other private information.

## Security notes

This server is powerful: depending on the enabled tools and your prompts, ChatGPT may inspect and modify local project files and invoke allowed development commands. Only register directories you trust and intend to make accessible.

- Keep the server and dependencies updated.
- Prefer authenticated access or a supported secure tunnel configuration. Do not publish an unauthenticated MCP endpoint.
- Use a unique, strong Bearer token if using the built-in Bearer authentication.
- Do not commit `.env`, tokens, or other secrets.
- File operations are constrained to the active registered repository; secret-file patterns are blocked by the security layer.
- Terminal commands run in the selected repository and are subject to the configured command controls, timeout, and output size limits. Read [docs/SECURITY.md](docs/SECURITY.md) before exposing tools remotely.
- Begin by using read-only tools and validate changes with Git status/diff. Keep backups or use version control before allowing write operations.

## Tests

Install project dependencies, then run:

```powershell
python -m pytest -v
```

Run the connection test:

```powershell
python scripts/test_connection.py
```

Run the diagnostic script:

```powershell
python scripts/doctor.py
```

Some tests may require a running server, valid repository configuration, or environment-specific resources. Review the individual test modules and ensure your local setup is correct before interpreting integration failures.

## Project layout

```text
MCP/
├── app/
│   ├── auth/                 # Bearer authentication middleware
│   ├── core/                 # Repository registry, sessions, security
│   ├── tools/                # MCP tool implementations
│   ├── config.py             # Environment-driven settings
│   └── main.py               # Server creation, routes, and tool registration
├── config/
│   ├── repositories.json     # Local registered repositories (machine-specific)
│   └── repositories.example.json
├── docs/
│   ├── ARCHITECTURE.md
│   ├── CHATGPT_SETUP.md
│   └── SECURITY.md
├── runtime/                  # Logs, PID files, current tunnel URL
├── scripts/
│   ├── doctor.py             # Environment and repository checks
│   ├── start.py              # Server start/stop/status
│   ├── tunnel.py             # HTTPS tunnel lifecycle
│   └── test_connection.py    # Connection check
├── tests/                    # Unit, integration, security, and E2E tests
├── start.bat                 # Main Windows one-click launcher
├── status_all.bat            # Status helper
├── stop_all.bat              # Stop helper
├── requirements.txt
└── pyproject.toml
```

## Recommended first prompts

Use the connected app in ChatGPT and start with:

```text
List my configured repositories. Do not read any secret files and do not modify anything.
```

```text
Select the repository named interview-copilot, inspect its architecture and Git status, then explain the main entry points. Do not change any files.
```

```text
Before making a code change, inspect the current Git status, explain the proposed change, edit only the selected repository, run the relevant tests, and show me the resulting diff. Do not commit or push.
```

---

### Additional guide

For a shorter, ChatGPT-only setup walkthrough and a reusable coding-agent prompt, see [docs/CHATGPT_SETUP.md](docs/CHATGPT_SETUP.md).
