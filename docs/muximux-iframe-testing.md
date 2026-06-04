# Muximux Iframe Testing

Use this workflow to validate that every Muximux entry loads through the real
public Cloudflare Access path at `https://apps.ghostship.io`.

The test uses `agent-browser` so it exercises an actual Chromium session. It
adds the Cloudflare Access service-token headers from `.envrc`, opens Muximux,
clicks each `data-content` menu entry, and records iframe status, frame URL,
frame title, browser console errors, request failures, and screenshots.

## Prerequisites

- Run from the repo root on a develop host with `agent-browser`.
- `.envrc` must export `CF_ACCESS_CLIENT_ID` and
  `CF_ACCESS_CLIENT_SECRET`.
- `node` and `npm` must be available.

Do not print the Access credential values. The audit script reads them from
`.envrc` and passes them as `CF-Access-Client-Id` and
`CF-Access-Client-Secret` headers.

## Run

```sh
scripts/audit-muximux-iframes
```

The default output directory is:

```text
/tmp/muximux-iframe-audit-<UTC timestamp>/
```

Useful options:

```sh
scripts/audit-muximux-iframes --out /tmp/muximux-audit
scripts/audit-muximux-iframes --services RomM,pyLoad,SSH
scripts/audit-muximux-iframes --session muximux-regression
```

Outputs:

- `results.json`: full machine-readable evidence.
- `summary.md`: table of service, status, frame URL, title, and notes.
- `<service>.png`: screenshot after selecting each Muximux entry.

## Status Meanings

- `loaded`: a visible iframe has a matching browser frame with non-empty title
  or body text.
- `blocked`: browser evidence contains `frame-ancestors` or
  `ERR_BLOCKED_BY_RESPONSE`, usually Cloudflare Access or CSP blocking a frame.
- `mixed-content`: an HTTPS Muximux page tried to load an HTTP iframe or
  redirect target.
- `blank-frame`: the iframe exists but the browser frame did not navigate.
- `blank-content`: the frame navigated but exposed no title or body text.
- `no-visible-iframe`: Muximux did not expose a visible iframe after clicking
  the entry.
- `error`: the audit script could not click or inspect the entry.

Non-2xx responses and console warnings are reported as notes, not automatic
failures. Some apps load successfully while still logging expected auth,
SignalR/WebSocket, or media-policy warnings.

## What To Fix

Patch only after browser evidence identifies the failing class.

- Cloudflare Access login inside an iframe: either make the target Access app
  accept the service token used by `.envrc`, or embed through a same-origin
  Muximux proxy path when that is the established pattern for the service.
- `frame-ancestors` or `X-Frame-Options`: fix the target service headers or the
  route that injects them.
- Mixed content: fix the target app's external URL, reverse-proxy headers, or
  redirect scheme so iframe navigations stay on HTTPS.
- Root-relative assets/API paths through a same-origin proxy: add focused
  sub-filter/base-path rewrites for that service only.

Keep screenshots and `results.json` with the deployment notes when making a
Muximux iframe change.
