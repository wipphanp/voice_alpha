"""Dashboard route — serves the operator UI."""

import json
from pathlib import Path

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse

from app.server.security import auth_enabled, is_valid_token

router = APIRouter()

UI_FILE = Path(__file__).parent.parent.parent.parent / "static" / "index.html"


# Minimal token-entry page shown when auth is enabled but no valid token
# was provided. Reloads the dashboard with the token as a query param.
_LOGIN_PAGE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<title>Alpha Bot AI — Sign in</title>
<style>
body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#0a0e1a;
color:#f1f5f9;display:flex;min-height:100vh;align-items:center;justify-content:center;margin:0}
.box{background:#111827;border:1px solid rgba(255,255,255,.08);border-radius:16px;
padding:32px;width:320px;text-align:center}
input{width:100%;padding:12px;margin:16px 0;border-radius:10px;border:1px solid #334;
background:#0a0e1a;color:#f1f5f9;box-sizing:border-box}
button{width:100%;padding:12px;border:none;border-radius:10px;cursor:pointer;
background:linear-gradient(135deg,#6366f1,#8b5cf6);color:#fff;font-weight:600}
h2{font-size:1.1rem;font-weight:600}.err{color:#ef4444;font-size:.85rem;min-height:1em}
</style></head><body>
<div class="box"><h2>📊 Alpha Bot AI</h2>
<p style="color:#94a3b8;font-size:.85rem">Enter your access token to continue</p>
<div class="err" id="err">__ERR__</div>
<input type="password" id="tok" placeholder="API token" autofocus
 onkeydown="if(event.key==='Enter')go()">
<button onclick="go()">Sign in</button></div>
<script>
function go(){var t=document.getElementById('tok').value.trim();
if(t)location.href='/?token='+encodeURIComponent(t);}
</script></body></html>"""


def _inject_token(html: str, token: str) -> str:
    """
    Inject the API token and a fetch wrapper into the dashboard so every
    same-origin /api request carries the X-API-Key header automatically.
    Injected into <head> so it runs before the page's own scripts.
    """
    snippet = (
        "<script>\n"
        f"window.__API_TOKEN__ = {json.dumps(token)};\n"
        "(function(){\n"
        "  var _f = window.fetch;\n"
        "  window.fetch = function(input, init){\n"
        "    init = init || {};\n"
        "    var url = (typeof input === 'string') ? input : (input && input.url) || '';\n"
        "    if (window.__API_TOKEN__ && url.indexOf('/api') !== -1){\n"
        "      var h = new Headers(init.headers || (typeof input!=='string' && input.headers) || {});\n"
        "      if(!h.has('X-API-Key')) h.set('X-API-Key', window.__API_TOKEN__);\n"
        "      init.headers = h;\n"
        "    }\n"
        "    return _f(input, init);\n"
        "  };\n"
        "})();\n"
        "</script>\n"
    )
    if "<head>" in html:
        return html.replace("<head>", "<head>\n" + snippet, 1)
    # Fallback: prepend if no <head> tag found.
    return snippet + html


@router.get("/", response_class=HTMLResponse)
async def home(request: Request, token: str | None = Query(default=None)):
    """Serve the operator dashboard (token-gated when auth is enabled)."""
    if not UI_FILE.exists():
        return HTMLResponse("<h1>Dashboard not found</h1>", status_code=404)

    html = UI_FILE.read_text(encoding="utf-8")

    if not auth_enabled():
        # Auth disabled — serve as-is (current behavior).
        return HTMLResponse(html)

    # Auth enabled: require a valid token via ?token=.
    if not is_valid_token(token):
        err = "Invalid token, try again." if token else ""
        return HTMLResponse(_LOGIN_PAGE.replace("__ERR__", err), status_code=401)

    return HTMLResponse(_inject_token(html, token))
