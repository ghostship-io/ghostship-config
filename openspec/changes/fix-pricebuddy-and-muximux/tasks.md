## 1. Muximux layout changes

- [x] 1.1 Update [modules/self-hosted/muximux.nix](/home/nixos/nixos-config/.worktrees/codex-fix-pricebuddy-and-muximux/modules/self-hosted/muximux.nix) so the generated service list places PriceBuddy on the main bar immediately after Grimmory.
- [x] 1.2 Remove the Honcho entry from the generated Muximux configuration while leaving the existing Homepage Honcho entry unchanged.

## 2. PriceBuddy runtime fixes

- [x] 2.1 Update [modules/self-hosted/pricebuddy.nix](/home/nixos/nixos-config/.worktrees/codex-fix-pricebuddy-and-muximux/modules/self-hosted/pricebuddy.nix) so `pricebuddy-token-sync` extracts the raw token portion before hashing and rewriting `PRICEBUDDY_API_TOKEN`.
- [x] 2.2 Add or refine implementation-level verification for PriceBuddy so deployment checks explicitly confirm env file generation, scraper reachability, and final bearer token format without treating known upstream auth or Cloudflare failures as host-env regressions.

## 3. Verification and rollout

- [x] 3.1 Run `nix flake check --no-build -L` in the repo worktree and run a targeted host evaluation or build for `chill-penguin` with a native Nix command before deployment.
- [ ] 3.2 Deploy the updated configuration to `chill-penguin`, then verify the live Muximux `settings.ini.php` no longer includes Honcho and places PriceBuddy after Grimmory on the main bar.
- [ ] 3.3 Verify the live PriceBuddy deployment on `chill-penguin` by checking container health, scraper reachability from the app container, and that `/srv/apps/pricebuddy/pricebuddy-agent.env` contains exactly one `<id>|<raw-token>` pair; repair any one-time corrupted host token artifact if needed.
- [x] 3.4 Update `README.md`, `CHANGELOG.md`, and `AGENTS.md` for any durable operator workflow, deployment, or service-behavior changes introduced by the implementation.
