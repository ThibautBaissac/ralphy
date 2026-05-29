# Deploying Ralphy on Fly.io

Last checked: 2026-05-29.

This document describes the recommended Fly.io deployment path for Ralphy:
a public, single-machine app with one persistent volume. It is intentionally
conservative because Ralphy is a stateful orchestration tool, not a stateless
web app.

## Recommendation

Use a **single Fly Machine with one persistent Fly Volume**.

That fits Ralphy's current architecture:

- Node/Express backend with WebSockets.
- SQLite at `DATABASE_PATH`.
- Per-user Claude/Codex/OpenCode credentials under configurable per-user roots.
- Task docs, uploads, recordings, prompt overrides, and templates under
  `RALPHY_ARCHIVE_ROOT`.
- Local git repositories and per-task worktrees.
- Long-running agent subprocesses.

Do **not** scale Ralphy horizontally as-is. Fly can create more Machines and
volumes, but it does not copy or synchronize volume data across those volumes.
SQLite, local git worktrees, provider credential files, and in-memory streaming
state all assume a single writer.

## Target Deployment

Use a public single-machine Fly app for a normal team deployment. Fly
terminates HTTPS, forwards HTTP and WebSocket traffic to the app, and the app
keeps all state on `/data`.

Good for:

- Small to medium internal teams.
- One shared Ralphy instance.
- GitHub webhook callbacks.
- A custom domain such as `ralphy.example.com`.

Constraints:

- One region, one running Machine.
- One attached volume.
- Deploys replace the Machine; active agent runs may be interrupted.

## Production Frontend Serving

Local development still runs two servers:

- `pnpm server`: backend API/WebSocket server.
- `pnpm client`: Vite frontend dev server.

For Fly, Ralphy uses one public process and one public port. `pnpm build`
builds the Vite frontend into `dist/`, and `pnpm start` runs the Express
server. When `NODE_ENV=production`, the server serves `dist/` and falls back to
`dist/index.html` for React Router routes while leaving `/api/*` routes to the
backend.

## Persistent Paths

Mount the Fly Volume at `/data` and point Ralphy's state there:

| Purpose | Environment variable | Recommended path |
| --- | --- | --- |
| SQLite database | `DATABASE_PATH` | `/data/ralphy/database/ralphy.db` |
| Task docs/uploads/recordings/prompt overrides | `RALPHY_ARCHIVE_ROOT` | `/data/ralphy/archive` |
| Claude credentials | `CLAUDE_CONFIG_ROOT` | `/data/ralphy/users` |
| Codex credentials | `CODEX_CONFIG_ROOT` | `/data/ralphy/users` |
| OpenCode credentials | `OPENCODE_CONFIG_ROOT` | `/data/ralphy/users` |
| Home directory for git/ssh/CLI config | `HOME` | `/data/home` |
| Repositories managed by Ralphy | none | `/data/repos/...` |

Use absolute repo paths such as `/data/repos/my-app` when creating projects in
Ralphy.

## Prerequisites

Install locally:

```bash
brew install flyctl
fly auth login
```

Choose:

- App name: `ralphy-prod` in examples below.
- Region: `cdg`.
- Volume size: start at `20GB` if you will clone real repos and keep worktrees.

## Dockerfile

The repo includes `Dockerfile`:

```dockerfile
# syntax=docker/dockerfile:1

FROM node:22-bookworm

RUN apt-get update \
  && apt-get install -y --no-install-recommends \
    bash \
    ca-certificates \
    curl \
    g++ \
    git \
    make \
    openssh-client \
    python3 \
    sqlite3 \
    tini \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN corepack enable

ARG CLAUDE_CODE_VERSION=2.1.156
ARG CODEX_CLI_VERSION=0.135.0

RUN npm install -g \
    @anthropic-ai/claude-code@${CLAUDE_CODE_VERSION} \
    @openai/codex@${CODEX_CLI_VERSION}

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile

COPY . .
RUN pnpm build

# Drop dev deps now that the frontend bundle is built. `tsx` stays because
# `pnpm start` runs `server/index.ts` directly; better-sqlite3 / node-pty keep
# their already-compiled native bindings.
RUN pnpm prune --prod

ENV NODE_ENV=production
ENV PORT=8080
ENV DISABLE_AUTOUPDATER=1
ENV HOME=/data/home
ENV DATABASE_PATH=/data/ralphy/database/ralphy.db
ENV RALPHY_ARCHIVE_ROOT=/data/ralphy/archive
ENV CLAUDE_CONFIG_ROOT=/data/ralphy/users
ENV CODEX_CONFIG_ROOT=/data/ralphy/users
ENV OPENCODE_CONFIG_ROOT=/data/ralphy/users

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8080/health || exit 1

ENTRYPOINT ["tini", "--"]
CMD ["pnpm", "start"]
```

Provider runtime note:

- Ralphy spawns provider runtimes as subprocesses.
- Anthropic ships as two separate packages: the Agent SDK
  (`@anthropic-ai/claude-agent-sdk`, installed by `pnpm install` as a regular
  dependency) and the CLI (`@anthropic-ai/claude-code`, installed globally by
  `npm install -g` in the Dockerfile because Ralphy spawns the `claude` binary).
  Codex is similar — the SDK is a regular dep, and the `codex` CLI is installed
  globally.
- Build args are pinned to exact versions for reproducible deploys. Override
  them at deploy time to upgrade a provider CLI:

```bash
fly deploy \
  --build-arg CLAUDE_CODE_VERSION=2.1.156 \
  --build-arg CODEX_CLI_VERSION=0.135.0
```

- `DISABLE_AUTOUPDATER=1` is set because container images should be immutable;
  update Claude Code by bumping the pinned `ARG` (or passing `--build-arg`) and
  rebuilding the image.
- Bump the pinned versions deliberately when you want to upgrade; avoid
  `latest`, which makes builds non-reproducible.
- If you install a CLI somewhere non-standard, set `CLAUDE_CLI_PATH` or
  `CODEX_CLI_PATH` as needed.
- OpenCode is not installed by this Dockerfile. If you later use OpenCode,
  install `opencode` in the image because Ralphy spawns `opencode serve`.

Use each provider's official install instructions and pin versions for
reproducibility. Do not rely on a CLI that only exists on your laptop.

## .dockerignore

The repo includes `.dockerignore`:

```gitignore
.git
node_modules
dist
coverage
playwright-report
server/database/ralphy.db
.env
.env.*
CLAUDE.local.md
CLAUDE.local.md.example
*.log
.DS_Store
.vscode
.idea
```

Do not bake local databases, tokens, SSH keys, or `.env` files into the image.

## fly.toml

Create the app without deploying:

```bash
fly launch --name ralphy-prod --region cdg --no-deploy
```

Then review the included `fly.toml`:

```toml
app = "ralphy-prod"
primary_region = "cdg"
kill_signal = "SIGTERM"
kill_timeout = 30

[build]
  dockerfile = "Dockerfile"

[env]
  NODE_ENV = "production"
  PORT = "8080"
  DISABLE_AUTOUPDATER = "1"
  HOME = "/data/home"
  DATABASE_PATH = "/data/ralphy/database/ralphy.db"
  RALPHY_ARCHIVE_ROOT = "/data/ralphy/archive"
  CLAUDE_CONFIG_ROOT = "/data/ralphy/users"
  CODEX_CONFIG_ROOT = "/data/ralphy/users"
  OPENCODE_CONFIG_ROOT = "/data/ralphy/users"

[http_service]
  internal_port = 8080
  force_https = true
  auto_stop_machines = "off"
  auto_start_machines = true
  min_machines_running = 1

  [http_service.concurrency]
    type = "connections"
    soft_limit = 50
    hard_limit = 80

  [[http_service.checks]]
    interval = "30s"
    timeout = "5s"
    grace_period = "20s"
    method = "GET"
    path = "/health"

[[mounts]]
  source = "ralphy_data"
  destination = "/data"
  initial_size = "20gb"
  snapshot_retention = 14
  auto_extend_size_threshold = 80
  auto_extend_size_increment = "5gb"
  auto_extend_size_limit = "100gb"

[[vm]]
  size = "shared-cpu-2x"
  memory = "2gb"
```

Notes:

- `auto_stop_machines = "off"` avoids interrupting idle but active agent work.
- `kill_timeout = 30` gives the server time to flush WebSocket sessions and let
  `startServer`'s orphan-recovery hook re-mark in-flight agent runs on the next
  boot (default 5s is too short for long-lived agent subprocesses).
- `type = "connections"` is better than request count for a WebSocket-heavy UI.
- `[[http_service.checks]]` polls `/health` so rolling deploys don't shift
  traffic to a Machine that hasn't finished booting (db init + orphan recovery
  can take a few seconds on a cold start).
- `shared-cpu-2x`/`2gb` is a reasonable starting point. Increase memory first if
  builds or provider CLIs get killed.

## Secrets

Set a real JWT secret:

```bash
fly secrets set JWT_SECRET="$(openssl rand -hex 64)"
```

Optional secrets:

```bash
fly secrets set OPENAI_API_KEY="..."              # voice transcription only
fly secrets set GITHUB_WEBHOOK_SECRET="..."       # PR-comment webhook trigger
fly secrets set ONESIGNAL_APP_ID="..."            # if push notifications are enabled
fly secrets set ONESIGNAL_REST_API_KEY="..."
```

`OPENAI_API_KEY` is consumed by the voice-transcription endpoint
(`server/services/transcription.ts`) and is safe to set globally:
`server/services/codexCredentials.ts` strips it (along with `OPENAI_BASE_URL`,
`OPENAI_ORG_ID`, `CODEX_HOME`, `CODEX_API_KEY`) from every Codex subprocess so
each user's `auth.json` stays authoritative.

Do not set `ANTHROPIC_API_KEY` as a global secret unless you are intentionally
changing the auth model — Ralphy's Claude credentials are per user and are
written under `/data/ralphy/users`.

## First Deploy

Deploy:

```bash
fly deploy
```

Check status and logs:

```bash
fly status
fly logs
```

Force single-machine scale:

```bash
fly scale count 1
fly scale show
```

Open:

```bash
fly apps open
```

The first account created through the setup screen becomes admin.

## Initialize The Volume

Open a shell:

```bash
fly ssh console
```

Create persistent directories:

```bash
mkdir -p /data/home/.ssh /data/ralphy/database /data/ralphy/archive /data/ralphy/users /data/repos /data/backups
chmod 700 /data/home /data/home/.ssh /data/ralphy/users
```

Configure git identity for the runtime user:

```bash
git config --global user.name "Ralphy"
git config --global user.email "ralphy@example.com"
```

Clone repositories into `/data/repos`:

```bash
cd /data/repos
git clone git@github.com:your-org/your-repo.git
```

### Private repos need an SSH key on the volume

The image ships **no** credentials, so cloning or pushing a private GitHub repo
requires an SSH key that lives on the persistent volume under `/data/home/.ssh`
(which is `$HOME/.ssh` at runtime). Never bake the key into the image — it would
land in the layer history and survive every deploy.

1. Generate a dedicated key on the volume (inside `fly ssh console`):

   ```bash
   ssh-keygen -t ed25519 -C "ralphy-prod" -f /data/home/.ssh/id_ed25519 -N ""
   chmod 700 /data/home/.ssh
   chmod 600 /data/home/.ssh/id_ed25519
   cat /data/home/.ssh/id_ed25519.pub
   ```

2. Register the **public** key with GitHub. Prefer a per-repo **deploy key**
   (Repo → Settings → Deploy keys → Add deploy key; tick *Allow write access*
   only if agents must push). For access to many repos, use a **machine user**
   or an org SSH key instead.

3. Pre-trust GitHub's host key so the first non-interactive clone doesn't hang
   on a prompt:

   ```bash
   ssh-keyscan github.com >> /data/home/.ssh/known_hosts
   ```

4. Clone over SSH (not HTTPS) so the key is used:

   ```bash
   cd /data/repos
   git clone git@github.com:your-org/your-repo.git
   ```

The key and `known_hosts` persist on the volume across deploys, so this is a
one-time setup per app. For HTTPS remotes instead, a GitHub fine-grained PAT in
a credential helper works too, but SSH deploy keys are the recommended path.

> **Why the key must be reachable from `/root/.ssh`, not just `$HOME`.** The
> container runs as **root**, and OpenSSH resolves `~/.ssh` from root's passwd
> home (`/root`) — it ignores the `HOME=/data/home` env var. So a key sitting in
> `/data/home/.ssh` is invisible to plain `ssh`/`git` unless `/root/.ssh` points
> at it. The Dockerfile bakes that symlink in
> (`ln -sfn /data/home/.ssh /root/.ssh`), so once the image carries it, plain
> `ssh -T git@github.com` and the PR agent's `git push` work as root with no
> extra flags. (Git itself *does* honor `$HOME`, so the git identity in
> `/data/home/.gitconfig` is read normally.)
>
> If you are on an **older image without the symlink**, verify with explicit
> paths instead:
>
> ```bash
> ssh -o UserKnownHostsFile=/data/home/.ssh/known_hosts \
>     -i /data/home/.ssh/id_ed25519 -o IdentitiesOnly=yes -T git@github.com
> # expect: "Hi <name>! You've successfully authenticated"
> ```

## Add Projects In Ralphy

A **project** in Ralphy is a database row pointing at a git repository **on the
machine's filesystem**. The repo must already be cloned onto the volume (see
[Initialize The Volume](#initialize-the-volume)) before you add it — Ralphy does
not clone for you, and the path is validated against what exists on disk.

In the UI:

1. **Log in as admin.** The first account created through the setup screen is
   admin; later users are created by an admin from `/admin`.
2. **Connect a provider** in Settings → Providers. Credentials are **per user**
   (stored under `/data/ralphy/users`), so every member authenticates their own
   Claude/Codex/OpenCode account — there is no shared key.
3. **Add a project** with the repo's **absolute path on the volume**, e.g.:

   ```text
   /data/repos/your-repo
   ```

   Use the real on-disk path under `/data/repos`, not a `~`-relative or local
   laptop path. Per-task git worktrees are created next to it at
   `/data/repos/your-repo-worktrees/task-<id>/`, so make sure the volume has
   headroom (see [Monitoring And Health](#monitoring-and-health)).
4. **Add project members** from `/admin` so other users can see and work the
   project. Membership is the authorization boundary — a user with no membership
   cannot access the project even if they can log in.
5. **Verify** by opening the project: it should list the repo's branches/tasks.
   If the project fails to load, confirm the path resolves on the machine:

   ```bash
   fly ssh console --app ralphy-prod
   git -C /data/repos/your-repo status
   ```

Each user still connects their own provider credentials before they can run
agents or chat.

## Custom Domain

Add a domain:

```bash
fly certs add ralphy.example.com
fly certs check ralphy.example.com
```

Follow the DNS instructions printed by Fly. For most direct setups, use A/AAAA
records. For subdomains, a CNAME to the app's `.fly.dev` host is often simpler.

Update GitHub webhook URLs, if used, to:

```text
https://ralphy.example.com/api/github/webhook
```

## Deployment Updates

Deploy application changes:

```bash
fly deploy
```

Useful operational commands:

```bash
fly logs
fly status
fly releases
fly ssh console
fly scale show
fly volumes list
```

Because Ralphy runs long-lived subprocesses, avoid deploying during active
agent runs. The startup recovery marks orphaned running agent runs as failed,
but users may need to restart interrupted work.

## Backups

Fly takes automatic daily snapshots for volumes by default and the config above
sets retention to 14 days. Treat those as recovery support, not your only
backup.

Create an application-level SQLite backup before risky deploys:

```bash
fly ssh console
sqlite3 /data/ralphy/database/ralphy.db ".backup '/data/backups/ralphy-$(date +%Y-%m-%d-%H%M%S).db'"
```

Create an on-demand Fly volume snapshot:

```bash
fly volumes list
fly volumes snapshots create <volume-id>
fly volumes snapshots list <volume-id>
```

To restore, create a new volume from a snapshot and attach a replacement
Machine in the same region. Do not restore over the live volume while Ralphy is
running.

## Monitoring And Health

Minimum checks:

```bash
fly logs
fly status
fly scale show
fly volumes list
```

Inside the Machine:

```bash
df -h /data
sqlite3 /data/ralphy/database/ralphy.db "PRAGMA integrity_check;"
git -C /data/repos/your-repo status
```

Watch disk usage. Repos, worktrees, recordings, SQLite transcripts, and provider
caches all grow over time.

## Cost Notes

As of the referenced Fly pricing page:

- Volumes are billed by provisioned capacity.
- Volume snapshots are billed by actual stored snapshot data, with a monthly
  free allowance.
- Machines are billed by CPU/RAM while running.

Keep one Machine running if you want Ralphy to handle webhooks and avoid cold
starts.

## Troubleshooting

### App starts but UI assets 404

Confirm the Express production static-serving change is present and that the
Docker build created `/app/dist`.

```bash
fly ssh console
ls -la /app/dist
```

### Login fails with JWT secret error

Set `JWT_SECRET`:

```bash
fly secrets set JWT_SECRET="$(openssl rand -hex 64)"
```

### Database disappears after deploy

`DATABASE_PATH` is not on the mounted volume. It must point under `/data`, for
example:

```text
/data/ralphy/database/ralphy.db
```

### Provider login works, but later runs fail

Check that provider credential roots are under `/data/ralphy/users` and that
the provider CLI binary exists in the image:

```bash
which claude || true
which codex || true
which opencode || true
ls -la /data/ralphy/users
```

### Private repo clone fails

Check SSH key permissions and known hosts:

```bash
chmod 700 /data/home/.ssh
chmod 600 /data/home/.ssh/id_ed25519
ssh -T git@github.com
```

### WebSocket disconnects after deploy

This is expected during Machine replacement. The client should reconnect. Avoid
deploying while conversations are actively streaming.

## Source References

- Fly Launch overview: https://fly.io/docs/reference/fly-launch/
- Deploy an app: https://fly.io/docs/launch/deploy/
- Docker on Fly.io: https://fly.io/docs/blueprints/working-with-docker/
- App configuration (`fly.toml`): https://fly.io/docs/reference/configuration/
- Fly Volumes overview: https://fly.io/docs/volumes/overview/
- Volume snapshots: https://fly.io/docs/volumes/snapshots/
- Scale Machine count: https://fly.io/docs/launch/scale-count/
- Scale CPU/RAM: https://fly.io/docs/launch/scale-machine/
- Secrets: https://fly.io/docs/apps/secrets/
- Custom domains: https://fly.io/docs/networking/custom-domain/
- Pricing: https://fly.io/docs/about/pricing/
