# Windows LocalControl GPT Bridge

Private FastAPI bridge for letting a Custom GPT call typed Windows control endpoints: file I/O, search, shell commands, process inspection, approvals, and audit logging.

## Quick Start

```bat
run.bat
```

`run.bat` creates `.venv` if needed, installs dependencies, and starts the API at `http://127.0.0.1:8765`.

This repo already has a generated `.env` with SHA-256 token hashes. The raw generated tokens are in the ignored local file `localcontrol-keys.txt`.

The app binds to `127.0.0.1:8765` by default. Expose it to ChatGPT only through an HTTPS tunnel or reverse proxy you control, such as a reserved ngrok domain or Cloudflare Tunnel.

## Test It

Open one terminal and run:

```bat
run.bat
```

Open a second terminal in this folder and run:

```bat
run.bat check
run.bat test
```

You can also open `http://127.0.0.1:8765/health` in a browser. It should show `auth_configured` and `approval_configured` as `true`.

## Allow-All Mode

For a fully local admin workflow, you can start the server with approvals disabled for dangerous operations:

```bat
run.bat --allow-all
```

Or with the public tunnel:

```bat
ngrok.bat --allow-all
```

In this mode, delete, process-kill, secret reads, and risky shell commands no longer require a separate approval step. Bearer auth, rate limits, output truncation, and audit logging still remain active. Check `http://127.0.0.1:8765/health` and look for `"allow_all": true`.

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

Overwriting existing files, deleting artifacts, and registering sensitive local paths require local approval unless you start with `run.bat --allow-all`.

## Terminal Sessions

Use persistent terminal sessions for multi-step command workflows. Every command is printed in the LocalControl server terminal and is also available through event polling.

```powershell
$session = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8765/terminal/sessions -Headers $headers -ContentType application/json -Body '{"shell":"powershell","cwd":"C:\\Temp","name":"work"}'
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8765/terminal/sessions/$($session.session_id)/exec" -Headers $headers -ContentType application/json -Body '{"command":"Get-ChildItem"}'
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8765/terminal/sessions/$($session.session_id)/events" -Headers $headers -ContentType application/json -Body '{"after_event_id":0,"max_events":100}'
```

For interactive commands, send more input with `/terminal/sessions/{session_id}/stdin`. Terminate finished sessions with `/terminal/sessions/{session_id}/terminate`.

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
4. Do not expose `LOCALCONTROL_APPROVAL_KEY` to ChatGPT. Approval/deny endpoints exist in the app but are intentionally omitted from the curated GPT schema.

The curated GPT schema is capped at 30 operations for the Custom GPT importer. The local API still exposes additional routes such as async job polling, process kill/list, advanced git actions, and approval inspection for local/manual use.

## Public ngrok Tunnel

Your assigned ngrok domain is configured in `ngrok.bat`:

```bat
ngrok.bat
```

That script starts LocalControl in the background, waits for `http://127.0.0.1:8765/health`, regenerates `gpt-actions.openapi.yaml` for `https://oblong-bonus-retrace.ngrok-free.dev`, then starts:

```bat
ngrok http --domain=oblong-bonus-retrace.ngrok-free.dev 127.0.0.1:8765
```

Keep the ngrok window open while your Custom GPT is using the API.

## Safety Model

- Every control endpoint requires bearer authentication.
- Risky operations require a second approval step: delete, process kill, sensitive path writes, long-running/destructive shell commands, and unredacted secret reads.
- Deletes are moved to `localcontrol-data/quarantine` by default. Permanent deletes require the same approval path.
- Shell calls require explicit shell choice, cwd, timeout, and output size limits.
- Outputs are truncated and common secrets are redacted unless an approved request explicitly asks for unredacted output.
- Audit logs are appended as JSONL at `localcontrol-data/audit.jsonl`.

## Approval Flow

If a risky operation is called without approval, the API returns HTTP 409:

```json
{
  "ok": false,
  "code": "approval_required",
  "details": {
    "approval": {
      "id": "...",
      "action": "fs.delete",
      "status": "pending"
    }
  }
}
```

Approve locally with the separate approval key:

```powershell
$headers = @{
  Authorization = "Bearer $env:LOCALCONTROL_API_KEY"
  "X-LocalControl-Approval-Key" = $env:LOCALCONTROL_APPROVAL_KEY
}
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8765/approval/<id>/approve -Headers $headers -Body '{"note":"approved locally"}' -ContentType 'application/json'
```

Then retry the original operation with `approval_id`.

## Windows Startup

After installing dependencies and creating `.env`, you can register a logon task:

```powershell
.\scripts\install-startup-task.ps1
```

## Development

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe .\scripts\export_openapi.py
```
