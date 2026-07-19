"""OAuth 2.1 PKCE shim for the MCP SSE endpoint.

Not a real multi-user authorization server -- there is exactly one
user. This exists purely to satisfy MCP clients (claude.ai, Claude
Desktop's Connectors UI) that only support OAuth-based remote
connectors, not raw bearer tokens.

The "password" on the /authorize screen IS the existing
MNEMOSYNE_MCP_TOKEN. The access_token handed back at the end of the
PKCE exchange is that same token, unchanged -- the real gate stays the
bearer-token check on /sse and /messages/ in mcp_server.py. This file
only ever gets mounted when that bearer gate is already active
(non-loopback host), so there's no new attack surface: anyone who could
complete this flow already had the token.
"""

import base64
import hashlib
import html
import secrets
import time
from typing import Dict, List, Tuple
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.routing import Route

_CODE_TTL_SECONDS = 5 * 60

# In-memory only: auth codes are single-use and expire in five minutes,
# so losing them on restart just means the client re-runs the PKCE
# dance once. No need for persistence.
_codes: Dict[str, Tuple[str, float]] = {}


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def build_oauth_routes(token: str, base_url: str) -> List[Route]:
    """Return Starlette routes implementing the OAuth PKCE shim.

    `token` is the existing MNEMOSYNE_MCP_TOKEN. `base_url` is the
    externally-reachable https:// origin (MNEMOSYNE_MCP_PUBLIC_URL),
    used to fill in the OAuth discovery documents.
    """

    async def discovery_authorization_server(_request: Request) -> JSONResponse:
        return JSONResponse(
            {
                "issuer": base_url,
                "authorization_endpoint": f"{base_url}/authorize",
                "token_endpoint": f"{base_url}/oauth/token",
                "response_types_supported": ["code"],
                "grant_types_supported": ["authorization_code"],
                "code_challenge_methods_supported": ["S256"],
            }
        )

    async def discovery_protected_resource(_request: Request) -> JSONResponse:
        return JSONResponse({"resource": base_url, "authorization_servers": [base_url]})

    async def authorize_get(request: Request) -> HTMLResponse:
        q = request.query_params
        fields = {
            name: html.escape(q.get(name, ""))
            for name in (
                "client_id",
                "redirect_uri",
                "state",
                "code_challenge",
                "code_challenge_method",
                "response_type",
            )
        }
        return HTMLResponse(
            f"""<!DOCTYPE html>
<html>
<head>
  <title>Mnemosyne MCP &#8212; Authorize</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body {{ font-family: sans-serif; max-width: 400px; margin: 4rem auto; padding: 1rem; }}
    input[type=password] {{ width: 100%; padding: .5rem; margin: .5rem 0 1rem; box-sizing: border-box; border: 1px solid #ccc; border-radius: 4px; font-size: 1rem; }}
    button {{ width: 100%; padding: .75rem; background: #1a73e8; color: #fff; border: none; border-radius: 4px; cursor: pointer; font-size: 1rem; }}
    button:hover {{ background: #1557b0; }}
  </style>
</head>
<body>
  <h2>Mnemosyne MCP</h2>
  <p>Enter the MCP token to authorize this client's access to your memory server.</p>
  <form method="POST" action="/authorize">
    <input type="hidden" name="client_id" value="{fields['client_id']}">
    <input type="hidden" name="redirect_uri" value="{fields['redirect_uri']}">
    <input type="hidden" name="state" value="{fields['state']}">
    <input type="hidden" name="code_challenge" value="{fields['code_challenge']}">
    <input type="hidden" name="code_challenge_method" value="{fields['code_challenge_method']}">
    <input type="hidden" name="response_type" value="{fields['response_type']}">
    <input type="password" name="password" placeholder="MCP Token" autofocus>
    <button type="submit">Authorize</button>
  </form>
</body>
</html>"""
        )

    async def authorize_post(request: Request):
        form = await request.form()
        password = form.get("password", "")
        redirect_uri = form.get("redirect_uri", "")
        state = form.get("state")
        code_challenge = form.get("code_challenge", "")
        code_challenge_method = form.get("code_challenge_method", "")

        if not redirect_uri or not secrets.compare_digest(str(password), token):
            return JSONResponse({"error": "invalid token"}, status_code=401)
        if code_challenge_method != "S256":
            return JSONResponse(
                {"error": "only S256 code_challenge_method is supported"}, status_code=400
            )

        code = _b64url(secrets.token_bytes(32))
        _codes[code] = (str(code_challenge), time.time() + _CODE_TTL_SECONDS)

        parts = urlparse(str(redirect_uri))
        params = dict(parse_qsl(parts.query))
        params["code"] = code
        if state:
            params["state"] = str(state)
        redirect_url = urlunparse(parts._replace(query=urlencode(params)))
        return RedirectResponse(redirect_url, status_code=302)

    async def oauth_token(request: Request) -> JSONResponse:
        form = await request.form()
        grant_type = form.get("grant_type")
        code = form.get("code")
        code_verifier = form.get("code_verifier")

        if grant_type != "authorization_code":
            return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)
        if not code or not code_verifier:
            return JSONResponse({"error": "invalid_request"}, status_code=400)

        stored = _codes.pop(str(code), None)
        if not stored or stored[1] < time.time():
            return JSONResponse({"error": "invalid_grant"}, status_code=400)

        challenge, _expires = stored
        verifier_hash = _b64url(hashlib.sha256(str(code_verifier).encode("ascii")).digest())
        if not secrets.compare_digest(verifier_hash, challenge):
            return JSONResponse({"error": "invalid_grant"}, status_code=400)

        return JSONResponse({"access_token": token, "token_type": "bearer"})

    return [
        Route(
            "/.well-known/oauth-authorization-server",
            discovery_authorization_server,
            methods=["GET"],
        ),
        Route(
            "/.well-known/oauth-protected-resource",
            discovery_protected_resource,
            methods=["GET"],
        ),
        Route("/authorize", authorize_get, methods=["GET"]),
        Route("/authorize", authorize_post, methods=["POST"]),
        Route("/oauth/token", oauth_token, methods=["POST"]),
    ]
