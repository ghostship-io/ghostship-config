## 1. Runtime Contract

- [x] 1.1 Update [hermes.nix](/home/nixos/nixos-config/modules/self-hosted/hermes.nix) to expose the missing non-secret utility-facing service URLs, including `CHANGEDETECTION_URL`, `CHAPTARR_URL`, `PRICEBUDDY_URL`, `RSS_BRIDGE_URL`, and `SYNOLOGY_URL=http://192.168.200.106:5000/`.
- [x] 1.2 Replace the current whole-bundle Hermes secret imports with selective projection that reads only the required utility auth values from existing service-local bundles and generated runtime env files, without introducing a duplicated Hermes-only projection bundle.
- [x] 1.3 Keep the Hermes router/provider env scope minimal by wiring only the current provider variables needed for the shipped fallback/router path.

## 2. Profile Browser Defaults

- [x] 2.1 Reuse the managed CloakBrowser profile inventory to resolve the `assistant`, `operations`, and `supervisor` profile ids and derive their `http://cloakbrowser:8080/api/profiles/<id>/cdp` URLs.
- [x] 2.2 Update the owned bootstrap path that rewrites `~/.hermes/profiles/<profile>/.env` so each managed profile receives its own `BROWSER_CDP_URL` instead of inheriting one shared browser default.
- [x] 2.3 Verify the design does not force the `assistant`, `operations`, or `supervisor` CloakBrowser profiles to stay launched continuously just to provide the default CDP targets.

## 3. Verification

- [x] 3.1 Run concrete verification commands for the local config shape, such as `nix eval .#nixosConfigurations.chill-penguin.config.virtualisation.oci-containers.containers.hermes.environment --json` and any focused evaluations needed to confirm the imported Hermes env sources.
- [x] 3.2 Validate the managed profile `.env` contract after the relevant image/bootstrap update by confirming `assistant`, `operations`, and `supervisor` each receive the expected `BROWSER_CDP_URL` and selected utility env values.
- [x] 3.3 Confirm the intended no-auth assumptions for qBittorrent and NZBGet still hold for Hermes, or adjust the contract if live validation shows they require credentials.

## 4. Documentation

- [x] 4.1 Update `README.md` to describe the managed Hermes utility/runtime env contract, selected secret-bundle imports, and per-profile CloakBrowser default browser wiring.
- [x] 4.2 Update `AGENTS.md` with the durable repo memory for Hermes utility env ownership, per-profile `BROWSER_CDP_URL` projection, and the chosen Synology base URL.
- [x] 4.3 Update `CHANGELOG.md` with the Hermes runtime env and profile-browser default changes once implementation lands.
