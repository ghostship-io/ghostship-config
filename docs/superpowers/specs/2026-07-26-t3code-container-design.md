# T3 Code Container Design

## Goal

Replace the Paseo workload on `chill-penguin` with upstream T3 Code while
preserving the established coding-container platform: persistent projects and
credentials, Codex and OpenCode providers, Antigravity alongside them, Ollama
Cloud access, nested Docker, Nix, user systemd services, maintenance, recovery,
and monitoring.

## Runtime

- Build the repo-owned `localhost/ghostship-t3code` image.
- Run the container as `t3code` with hostname `t3code.ghostship.io`.
- Serve `t3 serve` on its native internal port at `t3code:3773`.
- Keep the existing UID/GID 3000 account and `/srv/apps/paseo` state paths so
  the in-place replacement retains `/home/paseo`, `/workspace`, Docker data,
  and the isolated Nix store.
- Keep the service private to `ghostship_net`; external Cloudflare routing is
  managed outside this repository.

Upstream T3 Code requires one-time pairing for remote browsers. The
`t3code-pair` helper issues a one-hour pairing link for
`https://t3code.ghostship.io`; paired browsers retain their session cookie.

## Providers and tools

The four-hour maintenance service installs and updates:

- `t3`
- `@openai/codex`
- `opencode-ai`
- Antigravity `agy`

T3 Code uses its native Codex and OpenCode drivers. Antigravity remains
available directly in the container. A managed `codex_ollama` provider instance
launches Codex with `--local-provider=ollama` and the local authenticated Ollama
compatibility proxy. The ollama.com model catalog refreshes on the same
maintenance schedule. The image also contains `ollama`, `rg`, Git/Git LFS,
GitHub CLI, Node.js, Python, `uv`, build tools, Docker, Nix, and Cloudflared.

Every top-level Git repository in `/workspace` is registered with T3 Code
during setup.

## Services and recovery

The container uses systemd for setup, the T3 Code server, nested Docker, Nix,
the persistent user manager and D-Bus session, Secret Service, Ollama proxy,
bootstrap hooks, tool updates, restart gating, and health monitoring.

Maintenance and recovery query T3 Code's SQLite state and treat pending or
running turns as active. Unknown activity is not considered idle. Provider
health requires ready caches for Codex, OpenCode, and Codex through Ollama.
Configuration changes can be applied with `t3code-apply-config`, which validates
settings and rolls back to the last healthy snapshot on failure.

Persisted user services and quick tunnels remain available through
`t3code-user-units` and `t3code-tunnel`.

## Acceptance

1. Evaluate and build the `chill-penguin` configuration and T3 Code image.
2. Deploy the committed configuration to `chill-penguin`.
3. Verify the `t3code` container hostname, native port, root UI, user services,
   Docker, Nix, Ollama proxy, CLIs, provider caches, and project registration.
4. Verify all existing `/workspace` repositories and persisted credentials are
   available after migration.
