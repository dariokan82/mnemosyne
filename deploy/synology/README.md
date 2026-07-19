# Deploying Mnemosyne MCP on Trevor (Synology)

This is a from-source, [all]-extras build of this fork, deployed the same
way as the existing `mnemo-mcp` / `port-mcp` / `paperless-mcp` stacks on
Trevor. It runs **alongside** the legacy `mnemo-mcp` container until
migration is actually done -- nothing here touches that container or its
data under `/volume1/docker/mnemosine`.

## 1. Find your account's uid/gid

SSH into Trevor and run:

```sh
id <your-dsm-username>
```

You'll use the `uid=` / `gid=` values as `PUID`/`PGID` below, so the
container's files come out owned by your actual account (browsable in
File Station, editable over SSH) instead of a hardcoded guess. Same
convention as the `syncthing` and `plex` containers already on this host.

## 2. Deploy the stack in Portainer

Same git-stack pattern as the other *-mcp stacks:

1. Portainer → Stacks → Add stack → **Repository**
2. Repository URL: `https://github.com/dariokan82/mnemosyne`
3. Reference: `refs/heads/main`
4. Compose path: `docker-compose.yml` (repo root)
5. Environment variables:
   - `API_TOKEN` = a fresh secret, e.g. output of `openssl rand -hex 32`
     (this becomes the `Authorization: Bearer <token>` clients must send --
     see the security note in `mnemosyne/mcp_server.py`)
   - `PUID` / `PGID` = the values from step 1 (defaults to 1000/1000 if
     you skip this)
6. Deploy the stack.

The entrypoint reconciles the in-container user to PUID/PGID and chowns
`/data` to match on every start, so there's no manual host-side chown step
before first boot -- just make sure `/volume1/docker/mnemosyne` exists (or
let Docker create it, which it will as root and the entrypoint will then
fix on first start).

First boot downloads the fastembed model (~100MB) and the local GGUF
summarization model (~656MB, openbmb/MiniCPM5-1B-GGUF) from HuggingFace.
Both are cached under the bind mount (`HOME=/data/home`, see Dockerfile),
so this only happens once -- not on every restart/redeploy.

## 3. Create the project banks

Once the container shows healthy:

```sh
sh deploy/synology/init-banks.sh
```

Creates: `personal`, `candle`, `six-dimes`, `karma-police`, `signal-lost`,
`the-last-supper`, `quiet-mile`. Re-run any time you add a new project
slug -- it's idempotent.

## 4. Point the Cloudflare tunnel at it

The `cloudflared` container already on Trevor runs in `network_mode: host`
with a named-tunnel token; hostname routing is configured in the Cloudflare
Zero Trust dashboard (Networks → Tunnels → your tunnel → Public Hostname),
not in a compose file. Add a public hostname:

- Subdomain: `mnemosyne-mcp` (matches the `mnemosyne-mcp.belmont.lol` /
  `port-mcp.belmont.lol` naming already in use)
- Service: `http://localhost:8181`

## 5. Add it as a connector in claude.ai / Claude Desktop / Claude Code

All three point at the same SSE URL and bearer token:

- URL: `https://mnemosyne-mcp.belmont.lol/sse`
- Header: `Authorization: Bearer <API_TOKEN>`

- **claude.ai / Claude Desktop**: Settings → Connectors → Add custom
  connector → paste the URL. If it prompts for auth headers, add the
  `Authorization` header above; otherwise use whatever custom-header
  mechanism the connector UI currently exposes for non-OAuth remote MCP
  servers (this has shifted across Claude releases -- check the current
  "Add custom connector" dialog for a headers field).
- **Claude Code**: `claude mcp add --transport sse mnemosyne https://mnemosyne-mcp.belmont.lol/sse --header "Authorization: Bearer <API_TOKEN>"`

Per-call bank selection: every `mnemosyne_*` tool call accepts an optional
`bank` argument (falls back to `"default"` if omitted) -- one running
server serves all seven banks, no need for one container per bank.

## Constraints this setup respects

- No pip-on-host: everything ships in the image, built from this repo.
- `[all]` extras only -- no bare/degraded fallback.
- No `MNEMOSYNE_LLM_BASE_URL` -- stays on the local GGUF model, no remote
  LLM wiring.
- Existing `mnemo-mcp` container and its data are untouched.
