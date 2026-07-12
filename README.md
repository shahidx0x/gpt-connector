# Windows LocalControl GPT Bridge

Private FastAPI bridge for letting a Custom GPT call typed Windows control endpoints: file I/O, search, shell commands, process inspection, terminal sessions, and execution logs.

## Quick Start

```bat
run.bat
```

`run.bat` creates `.venv` if needed, installs dependencies, opens the prelaunch settings UI, and starts the main app after you click **Start LocalControl**.

The default start mode is API + ngrok tunnel. To open settings with API-only selected:

```bat
run.bat serve
```

This repo already has a generated `.env` with SHA-256 token hashes. The raw generated tokens are in the ignored local file `localcontrol-keys.txt`.

The app binds to `127.0.0.1:8765` by default. Expose it to ChatGPT only through an HTTPS tunnel or reverse proxy you control, such as a reserved ngrok domain or Cloudflare Tunnel.

## Test It

Open one terminal and run:

```bat
run.bat
```

The settings page opens first on a temporary `127.0.0.1` port. Configure the API key, port, and ngrok token, then click **Start LocalControl**.

Open a second terminal in this folder and run:

```bat
run.bat check
run.bat test
```

You can also open `http://127.0.0.1:8765/health` in a browser. It should show `auth_configured` and `approval_configured` as `true`.

## GUI Control Panel

Startup now shows the settings UI before the main app starts. After startup, the same control panel is also available from the running app:

```text
http://127.0.0.1:8765/ui
```

The UI uses the same bearer token as the API. It can refresh runtime config, reveal or randomize the API key, update the saved port, set the ngrok authtoken/domain/public URL, and run PowerShell or `cmd.exe` terminal sessions through the existing terminal API.

Secret values are masked by default. Click **Reveal** after entering the bearer token when you need to show or copy the current API key or ngrok authtoken. Port and tunnel setting changes are saved to `.env`; port and active tunnel changes take effect on restart.

## Full-Control Mode

LocalControl now runs in full-control mode by default. Authenticated requests execute directly; delete, process-kill, secret reads, git reset, artifact overwrite/delete, and shell commands do not require a second approval step.

```bat
run.bat
```

Bearer auth, rate limits, output truncation, redaction defaults, and in-memory execution logging still remain active. Check `http://127.0.0.1:8765/health` and look for `"full_control": true`.

## Multi-Project Control

Register project roots once, then use `project_id` in shell, terminal, search, and git commands instead of repeating absolute paths:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8765/projects/register -Headers $headers -ContentType application/json -Body '{"project_id":"app1","name":"App One","path":"E:\\PROJECTS\\AppOne"}'
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8765/projects/list -Headers $headers
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8765/shell/run -Headers $headers -ContentType application/json -Body '{"project_id":"app1","shell":"powershell","command":"git status"}'
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8765/search/content -Headers $headers -ContentType application/json -Body '{"project_id":"app1","pattern":"TODO"}'
```

If both `project_id` and a relative `cwd` or `root` are provided, the relative path is resolved inside the registered project root.

Git does not have a separate API surface. Use the locally installed `git` executable through `/shell/run`, usually with `project_id` set to the registered repository root.

## Worker Pool

Shell commands run through a bounded worker pool. The default worker count is `max(4, CPU cores * 4)`, which lets external programs and shell commands run across available CPU cores without creating unlimited command threads. Override it with:

```powershell
$env:LOCALCONTROL_MAX_SHELL_WORKERS = "32"
```

`/health` reports `cpu_count` and `max_shell_workers`.

## Artifacts

Artifacts are small/medium files managed under `localcontrol-data/artifacts` and addressed by `artifact_id`. The limit defaults to 50 MB.

Create text, fetch a URL, or register a local file:

```powershell
$headers = @{ Authorization = "Bearer $env:LOCALCONTROL_API_KEY" }
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8765/artifacts/create_text -Headers $headers -ContentType application/json -Body '{"name":"note.txt","content":"hello"}'
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8765/artifacts/fetch_url -Headers $headers -ContentType application/json -Body '{"url":"https://example.com/file.txt"}'
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8765/artifacts/from_path -Headers $headers -ContentType application/json -Body '{"path":"C:\\Temp\\input.txt","copy":true}'
```

Write or download an artifact:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8765/artifacts/<artifact_id>/write_to_path -Headers $headers -ContentType application/json -Body '{"path":"C:\\Temp\\output.txt"}'
Invoke-WebRequest -Uri http://127.0.0.1:8765/artifacts/<artifact_id>/download -Headers $headers -OutFile C:\Temp\downloaded.txt
```

Overwriting existing files, deleting artifacts, and registering local paths execute directly for authenticated callers.

## Terminal Sessions

Use persistent terminal sessions for multi-step command workflows. Every command is printed in the LocalControl server terminal and is also available through event polling.

```powershell
$session = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8765/terminal/sessions -Headers $headers -ContentType application/json -Body '{"shell":"powershell","cwd":"C:\\Temp","name":"work"}'
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8765/terminal/sessions/$($session.session_id)/exec" -Headers $headers -ContentType application/json -Body '{"command":"Get-ChildItem"}'
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8765/terminal/sessions/$($session.session_id)/events" -Headers $headers -ContentType application/json -Body '{"after_event_id":0,"max_events":100}'
```

For interactive commands, send more input with `/terminal/sessions/{session_id}/stdin`. Terminate finished sessions with `/terminal/sessions/{session_id}/terminate`.

## Execution Logs

All `/shell/run` commands execute through the job manager, including synchronous calls. Each command has a `job_id`, and command, stdout, stderr, stdin, and system events are stored in a unified in-memory execution log.

Poll recent events:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8765/execution/logs -Headers $headers -ContentType application/json -Body '{"after_event_id":0,"max_events":100}'
```

Poll one command or terminal session:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8765/execution/logs -Headers $headers -ContentType application/json -Body '{"run_id":"<job_id-or-session_id>","max_events":100}'
```

## Architecture

The app is organized around a small FastAPI composition layer and focused backend operation modules:

```text
localcontrol/
  api/
    app.py              FastAPI app factory, middleware, exception handlers
    deps.py             Shared request helpers
    routes/             Route modules grouped by API domain
  *_ops.py              Filesystem, shell, terminal, process, artifact, and system operations
  execution_log.py      Unified command/session event log
  project_ops.py        Multi-project registry and path resolution
  models.py             Pydantic request/response schemas
  main.py               Compatibility import for localcontrol.main:app
```

Routes stay thin: they validate requests and call one operation module. Runtime execution logic remains outside the API package so command handling, terminal sessions, project routing, and logging can evolve independently.

## Custom GPT Setup

1. Export the curated schema:

   ```powershell
   .\.venv\Scripts\python.exe .\scripts\export_openapi.py --server-url https://YOUR-RESERVED-NGROK-DOMAIN.ngrok-free.app
   ```

2. In your Custom GPT action settings, import `gpt-actions.openapi.yaml` or paste this public schema URL when the tunnel is running:

   ```text
   https://oblong-bonus-retrace.ngrok-free.dev/gpt-actions.openapi.yaml
   ```

   Short alias:

   ```text
   https://oblong-bonus-retrace.ngrok-free.dev/gpt-actions.yml
   ```

3. Set authentication to API key / bearer token using `LOCALCONTROL_API_KEY` from `localcontrol-keys.txt`.
4. Register project roots with `/projects/register` and use `/execution/logs` after `/shell/run` or terminal operations to retrieve tracked output.

The curated GPT schema is capped at 30 operations for the Custom GPT importer. The local API still exposes additional routes such as process kill/list and legacy approval inspection for local/manual compatibility.

## Public ngrok Tunnel

Start LocalControl and ngrok together with either command:

```bat
run.bat tunnel
ngrok.bat
```

Tunnel mode starts LocalControl in the background, waits for `http://127.0.0.1:8765/health`, starts ngrok, detects the public HTTPS URL, regenerates `gpt-actions.openapi.yaml` for that URL, and keeps both processes alive until the tunnel exits.

If ngrok is not installed, `run.bat tunnel` downloads the Windows ngrok ZIP and installs `ngrok.exe` locally under `.local-tools\ngrok\`. That folder is ignored by git.

ngrok requires an account authtoken. Tunnel mode uses `LOCALCONTROL_NGROK_AUTHTOKEN` or `NGROK_AUTHTOKEN` when set; otherwise it prompts and saves the token with `ngrok config add-authtoken`.

```powershell
$env:LOCALCONTROL_NGROK_AUTHTOKEN = "paste-your-ngrok-token-here"
```

For a reserved ngrok domain, set one of these before starting:

```powershell
$env:LOCALCONTROL_NGROK_DOMAIN = "oblong-bonus-retrace.ngrok-free.dev"
# or:
$env:LOCALCONTROL_PUBLIC_URL = "https://oblong-bonus-retrace.ngrok-free.dev"
```

Optional:

```powershell
$env:LOCALCONTROL_NGROK_EXE = "C:\Tools\ngrok.exe"
$env:LOCALCONTROL_NGROK_DOWNLOAD_URL = "https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-windows-amd64.zip"
$env:LOCALCONTROL_NGROK_API_PORT = "4040"
$env:LOCALCONTROL_NGROK_URL_TIMEOUT_SECONDS = "300"
```

If no reserved domain is configured, tunnel mode uses ngrok's local API to read the random public HTTPS URL and exports the GPT schema for that URL. Keep the tunnel window open while your Custom GPT is using the API.

If ngrok rejects the token, exits early, or never publishes a public URL, the launcher prompts for a fresh token and retries up to three times. Corrected tokens are saved back to `.env` as `LOCALCONTROL_NGROK_AUTHTOKEN` and to ngrok's own config. If ngrok stays at `Session Status connecting`, the launcher waits up to `LOCALCONTROL_NGROK_URL_TIMEOUT_SECONDS` and prints the last local API status. Usually that means ngrok is still negotiating, the account/token has a problem, or outbound network/firewall access is blocked. You can raise the timeout or set `LOCALCONTROL_PUBLIC_URL` / `LOCALCONTROL_NGROK_DOMAIN` when you already know the public URL.

## Full-Control Execution Model

- Every control endpoint requires bearer authentication.
- Authenticated control operations execute directly without risk assessment or approval prompts.
- Deletes execute directly. No quarantine directory is maintained.
- Shell calls run through a CPU-aware worker pool with explicit shell choice, project/cwd, timeout, and output size limits.
- `cmd.exe` and PowerShell launch with non-profile command flags optimized for automation.
- Outputs are tracked in `/execution/logs`, truncated in direct responses, and common secrets are redacted unless `include_secrets=true`.
- Persistent audit JSONL logging is disabled; command/session output remains available in memory through `/execution/logs`.

## Windows Startup

After installing dependencies and creating `.env`, you can register a logon task:

```powershell
.\scripts\install-startup-task.ps1
```

To start the API and ngrok automatically at logon:

```powershell
.\scripts\install-startup-task.ps1 -Tunnel -NgrokDomain oblong-bonus-retrace.ngrok-free.dev
```

For unattended startup, set the token before registering the task or pass it once:

```powershell
.\scripts\install-startup-task.ps1 -Tunnel -NgrokDomain oblong-bonus-retrace.ngrok-free.dev -NgrokAuthtoken "paste-your-ngrok-token-here"
```

## Windows EXE Bundle

Build a distributable Windows executable with PyInstaller:

```bat
run.bat build-exe
```

That creates:

```text
dist\LocalControl\LocalControl.exe
```

The build bundles `ngrok.exe` by default. If ngrok is not already available, the build downloads it to `.local-tools\ngrok\ngrok.exe` first, then includes it in the PyInstaller output.

Double-clicking the packaged executable starts tunnel mode by default. Use the executable directly:

```powershell
.\dist\LocalControl\LocalControl.exe
.\dist\LocalControl\LocalControl.exe tunnel
.\dist\LocalControl\LocalControl.exe schema --server-url https://YOUR-NGROK-DOMAIN.ngrok-free.app
```

The exe reads `.env` from the current working directory, and also from the executable folder when launched from the bundled `dist\LocalControl` directory. It can still auto-download ngrok into `.local-tools\ngrok` when tunnel mode needs it.

For a single-file executable:

```powershell
.\scripts\build-exe.ps1 -OneFile
```

That creates `dist\LocalControl.exe`; double-clicking it also starts tunnel mode. To build without bundling ngrok:

```powershell
.\scripts\build-exe.ps1 -OneFile -NoBundleNgrok
```

## GitHub Release Build

The repository includes a GitHub Actions workflow that builds the standalone Windows x64 executable with bundled ngrok and publishes release assets.

Create a release by pushing a version tag:

```powershell
git tag v0.1.0
git push origin v0.1.0
```

You can also run **Release Standalone Windows EXE** manually from the GitHub Actions tab. The release contains:

```text
LocalControl-windows-x64-standalone.exe
LocalControl-windows-x64-standalone.zip
LocalControl-windows-x64-standalone.exe.sha256
LocalControl-windows-x64-standalone.zip.sha256
```

The released executable is the one-file PyInstaller build. It includes `ngrok.exe` and starts tunnel mode by default when launched without arguments.

## Development

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe .\scripts\export_openapi.py
```
