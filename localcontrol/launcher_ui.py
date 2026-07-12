from __future__ import annotations

import json
import secrets
import threading
import time
import webbrowser
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Literal

from .config_store import config_snapshot, update_config

Mode = Literal["serve", "tunnel"]


@dataclass(frozen=True)
class LauncherResult:
    action: Literal["start", "cancel"]
    mode: Mode


class _LauncherState:
    def __init__(self, default_mode: Mode) -> None:
        self.default_mode = default_mode
        self.nonce = secrets.token_urlsafe(18)
        self.done = threading.Event()
        self.result: LauncherResult | None = None
        self.lock = threading.Lock()


def _coerce_port(value: Any) -> int | None:
    if value in {None, ""}:
        return None
    port = int(value)
    if port < 1 or port > 65535:
        raise ValueError("Port must be between 1 and 65535.")
    return port


def _clean_optional(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned if cleaned else None


def _handle_save(payload: dict[str, Any]) -> dict[str, Any]:
    current = config_snapshot(reveal_secrets=True)
    api_key = _clean_optional(payload.get("api_key"))
    randomize_api_key = bool(payload.get("randomize_api_key")) or (
        not api_key and not current.get("api_key", {}).get("configured")
    )
    return update_config(
        port=_coerce_port(payload.get("port")),
        api_key=api_key,
        randomize_api_key=randomize_api_key,
        ngrok_authtoken=_clean_optional(payload.get("ngrok_authtoken")),
        ngrok_domain=str(payload.get("ngrok_domain") or "").strip(),
        public_url=str(payload.get("public_url") or "").strip(),
        reveal_secrets=True,
    )


def _html(nonce: str, default_mode: Mode) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>GPT-Connect Launcher</title>
  <style>
    :root {{
      color-scheme: dark;
      --bg: #101316;
      --panel: #1a1f24;
      --line: #313942;
      --text: #edf2f5;
      --muted: #9facb8;
      --accent: #35a37f;
      --blue: #4c8bd6;
      --danger: #dd6b6b;
      --sans: "Segoe UI", system-ui, sans-serif;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      background: var(--bg);
      color: var(--text);
      font-family: var(--sans);
    }}
    main {{
      width: min(960px, calc(100vw - 28px));
      margin: 0 auto;
      padding: 24px 0;
    }}
    header {{
      display: flex;
      align-items: flex-end;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 16px;
    }}
    h1 {{ margin: 0; font-size: 24px; letter-spacing: 0; }}
    h2 {{ margin: 0 0 12px; font-size: 15px; letter-spacing: 0; }}
    .sub {{ color: var(--muted); margin-top: 4px; }}
    .layout {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 14px;
    }}
    .panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 16px;
    }}
    .grid {{ display: grid; gap: 12px; }}
    .two {{ grid-template-columns: 1fr 1fr; }}
    label {{
      display: grid;
      gap: 6px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0;
    }}
    input, select, button {{
      font: inherit;
      min-height: 36px;
      border-radius: 6px;
    }}
    input, select {{
      width: 100%;
      border: 1px solid var(--line);
      background: #0c0f12;
      color: var(--text);
      padding: 7px 10px;
    }}
    button {{
      border: 1px solid var(--line);
      background: #232a31;
      color: var(--text);
      padding: 0 13px;
      cursor: pointer;
    }}
    button:hover {{ border-color: var(--blue); }}
    .primary {{
      background: var(--accent);
      border-color: var(--accent);
      color: #06110d;
      font-weight: 800;
    }}
    .danger:hover {{ border-color: var(--danger); }}
    .actions {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      align-items: center;
    }}
    .footer {{
      margin-top: 14px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      flex-wrap: wrap;
    }}
    .message {{
      color: var(--muted);
      min-height: 20px;
      overflow-wrap: anywhere;
    }}
    .message.ok {{ color: #a9e8d0; }}
    .message.error {{ color: #ffb3b3; }}
    @media (max-width: 760px) {{
      header, .layout, .two {{ grid-template-columns: 1fr; display: grid; }}
      header {{ align-items: start; }}
    }}
  </style>
</head>
<body>
  <main>
    <header>
      <div>
        <h1>GPT-Connect Settings</h1>
        <div class="sub">Configure first. Start the main app after settings are ready.</div>
      </div>
      <button id="refresh" type="button">Refresh</button>
    </header>

    <div class="layout">
      <section class="panel grid">
        <h2>Startup</h2>
        <div class="two grid">
          <label>Run mode
            <select id="mode">
              <option value="tunnel">API + ngrok tunnel</option>
              <option value="serve">API only</option>
            </select>
          </label>
          <label>Port
            <input id="port" type="number" min="1" max="65535">
          </label>
        </div>
        <label>Config file
          <input id="env-path" type="text" readonly>
        </label>
      </section>

      <section class="panel grid">
        <h2>Authentication</h2>
        <label>API key
          <input id="api-key" type="password" autocomplete="off" spellcheck="false">
        </label>
        <div class="actions">
          <button id="toggle-api" type="button">Show</button>
          <button id="random-api" type="button">Randomize</button>
          <button id="copy-api" type="button">Copy</button>
        </div>
      </section>

      <section class="panel grid">
        <h2>Ngrok</h2>
        <label>Authtoken
          <input id="ngrok-token" type="password" autocomplete="off" spellcheck="false">
        </label>
        <div class="actions">
          <button id="toggle-ngrok" type="button">Show</button>
          <button id="copy-ngrok" type="button">Copy</button>
        </div>
        <label>Reserved domain
          <input id="ngrok-domain" type="text" spellcheck="false">
        </label>
        <label>Public URL
          <input id="public-url" type="url" spellcheck="false">
        </label>
      </section>

      <section class="panel grid">
        <h2>Launch</h2>
        <div class="message" id="message">Waiting for settings.</div>
        <div class="actions">
          <button id="save" type="button">Save Settings</button>
          <button id="start" type="button" class="primary">Start GPT-Connect</button>
          <button id="cancel" type="button" class="danger">Cancel</button>
        </div>
      </section>
    </div>

    <div class="footer">
      <div class="message">This prelaunch page runs on 127.0.0.1 and closes after Start.</div>
    </div>
  </main>

  <script>
    const nonce = {json.dumps(nonce)};
    const defaultMode = {json.dumps(default_mode)};
    const $ = (id) => document.getElementById(id);

    function setMessage(text, kind = "") {{
      const node = $("message");
      node.textContent = text;
      node.className = `message ${{kind}}`.trim();
    }}

    async function request(path, payload) {{
      const response = await fetch(`/api/${{nonce}}/${{path}}`, {{
        method: "POST",
        headers: {{ "Content-Type": "application/json" }},
        body: JSON.stringify(payload || {{}})
      }});
      const data = await response.json();
      if (!response.ok) {{
        throw new Error(data.error || `HTTP ${{response.status}}`);
      }}
      return data;
    }}

    function applyConfig(config) {{
      $("mode").value = config.mode || defaultMode;
      $("port").value = config.port || 8765;
      $("env-path").value = config.env_path || "";
      $("api-key").value = config.api_key?.value || "";
      $("ngrok-token").value = config.ngrok_authtoken?.value || "";
      $("ngrok-domain").value = config.ngrok_domain || "";
      $("public-url").value = config.public_url || "";
    }}

    function collect(randomize = false) {{
      return {{
        mode: $("mode").value,
        port: Number($("port").value),
        api_key: $("api-key").value.trim(),
        randomize_api_key: randomize,
        ngrok_authtoken: $("ngrok-token").value.trim(),
        ngrok_domain: $("ngrok-domain").value.trim(),
        public_url: $("public-url").value.trim()
      }};
    }}

    async function loadConfig() {{
      try {{
        const data = await request("config", {{}});
        applyConfig(data);
        setMessage("Loaded current settings.", "ok");
      }} catch (error) {{
        setMessage(error.message, "error");
      }}
    }}

    async function saveSettings(randomize = false) {{
      const data = await request("save", collect(randomize));
      applyConfig(data);
      setMessage("Settings saved.", "ok");
      return data;
    }}

    async function start() {{
      try {{
        await request("start", collect(false));
        setMessage("Starting GPT-Connect. You can close this browser tab.", "ok");
      }} catch (error) {{
        setMessage(error.message, "error");
      }}
    }}

    function toggleInput(id, buttonId) {{
      const input = $(id);
      input.type = input.type === "password" ? "text" : "password";
      $(buttonId).textContent = input.type === "password" ? "Show" : "Hide";
    }}

    function randomKey() {{
      const bytes = new Uint8Array(32);
      crypto.getRandomValues(bytes);
      $("api-key").value = "lc_" + Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
      setMessage("Generated a new API key. Click Save or Start to persist it.", "ok");
    }}

    async function copyInput(id) {{
      const value = $(id).value;
      if (!value) {{
        setMessage("Nothing to copy.", "error");
        return;
      }}
      await navigator.clipboard.writeText(value);
      setMessage("Copied.", "ok");
    }}

    $("refresh").addEventListener("click", loadConfig);
    $("save").addEventListener("click", () => saveSettings(false));
    $("start").addEventListener("click", start);
    $("cancel").addEventListener("click", () => request("cancel", {{}}).then(() => setMessage("Canceled.", "ok")));
    $("toggle-api").addEventListener("click", () => toggleInput("api-key", "toggle-api"));
    $("toggle-ngrok").addEventListener("click", () => toggleInput("ngrok-token", "toggle-ngrok"));
    $("random-api").addEventListener("click", randomKey);
    $("copy-api").addEventListener("click", () => copyInput("api-key"));
    $("copy-ngrok").addEventListener("click", () => copyInput("ngrok-token"));

    $("mode").value = defaultMode;
    loadConfig();
  </script>
</body>
</html>"""


def run_prelaunch_ui(default_mode: Mode, *, open_browser: bool = True) -> LauncherResult:
    state = _LauncherState(default_mode)

    class Handler(BaseHTTPRequestHandler):
        server_version = "GPTConnectLauncher/1.0"

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length") or "0")
            if length <= 0:
                return {}
            return json.loads(self.rfile.read(length).decode("utf-8"))

        def do_GET(self) -> None:
            if self.path in {"/", ""}:
                self.send_response(302)
                self.send_header("Location", f"/{state.nonce}")
                self.end_headers()
                return
            if self.path.rstrip("/") != f"/{state.nonce}":
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            body = _html(state.nonce, state.default_mode).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:
            prefix = f"/api/{state.nonce}/"
            if not self.path.startswith(prefix):
                self._send_json({"error": "Invalid launcher session."}, status=404)
                return
            action = self.path[len(prefix) :]
            try:
                payload = self._read_json()
                if action == "config":
                    snapshot = config_snapshot(reveal_secrets=True)
                    snapshot["mode"] = state.default_mode
                    self._send_json(snapshot)
                    return
                if action == "save":
                    saved = _handle_save(payload)
                    saved["mode"] = payload.get("mode") or state.default_mode
                    self._send_json(saved)
                    return
                if action == "start":
                    saved = _handle_save(payload)
                    mode = payload.get("mode") if payload.get("mode") in {"serve", "tunnel"} else state.default_mode
                    with state.lock:
                        state.result = LauncherResult(action="start", mode=mode)
                        state.done.set()
                    saved["mode"] = mode
                    self._send_json(saved)
                    threading.Thread(target=self.server.shutdown, daemon=True).start()
                    return
                if action == "cancel":
                    with state.lock:
                        state.result = LauncherResult(action="cancel", mode=state.default_mode)
                        state.done.set()
                    self._send_json({"ok": True})
                    threading.Thread(target=self.server.shutdown, daemon=True).start()
                    return
                self._send_json({"error": "Unknown action."}, status=404)
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=400)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    url = f"http://127.0.0.1:{server.server_port}/{state.nonce}"
    print()
    print(f"GPT-Connect settings UI: {url}")
    print("Configure settings in the browser, then click Start GPT-Connect.")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    finally:
        server.server_close()

    return state.result or LauncherResult(action="cancel", mode=default_mode)
