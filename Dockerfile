# syntax=docker/dockerfile:1

FROM node:22-bookworm

RUN apt-get update \
  && apt-get install -y --no-install-recommends \
    bash \
    ca-certificates \
    curl \
    git \
    g++ \
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

# The app runs as root, and OpenSSH resolves `~/.ssh` from root's passwd home
# (/root), ignoring $HOME. Symlink it to the volume so git-over-SSH (clone,
# fetch, the PR agent's push) uses the key + known_hosts stored on /data. The
# target is created at runtime when the volume mounts; the symlink survives
# deploys because it lives in the image.
RUN ln -sfn /data/home/.ssh /root/.ssh

ENV NODE_ENV=production
ENV PORT=8080
ENV DISABLE_AUTOUPDATER=1
# The container runs as root; Claude Code blocks --dangerously-skip-permissions
# (Ralphy's bypassPermissions mode) as root unless it thinks it's sandboxed.
# The isolated single-tenant Machine is that sandbox — without this, every
# agent subprocess exits 1 immediately.
ENV IS_SANDBOX=1
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
