"""Serve the desktop viewer at the site root and Selkies under /desktop/.

Applied at image build to the baseimage's nginx template
(/defaults/default.conf), so the viewer shares the desktop's origin and its
Cloudflare Access protection. Fails the build if the template changes shape.

- / proxies to the viewer (sessions, apps and the Desktop mode).
- Selkies' own locations move from SUBFOLDER to /desktop/, written here so
  nginx never depends on the env; the selkies server learns the same prefix
  from SUBFOLDER=/desktop/ (agent-desktop.nix). The viewer frames /desktop/.
- /agents and /agents/... (the viewer's old address) redirect to /.
- Redirects stay relative. nginx otherwise builds them from its own listen
  port, e.g. /agents -> http://desktop.ghostship.io:3000/agents/.
"""
import sys

MARK = "  # ghostship: desktop viewer at the site root\n"
PREFIX = "/desktop/"
BLOCK = MARK + """  absolute_redirect       off;
  location = /agents {
    return 301 /;
  }
  location /agents/ {
    return 301 /;
  }
  location / {
    proxy_set_header        Upgrade $http_upgrade;
    proxy_set_header        Connection "upgrade";
    proxy_set_header        Host $http_host;
    proxy_set_header        X-Forwarded-Proto $scheme;
    proxy_http_version      1.1;
    proxy_read_timeout      3600s;
    proxy_send_timeout      3600s;
    proxy_buffering         off;
    client_max_body_size    1M;
    proxy_pass              http://127.0.0.1:7090;
  }
"""
ANCHOR = "  error_page 500 502 503 504 /50x.html;\n"

path = sys.argv[1]
text = open(path, encoding="utf-8").read()
if MARK in text:
    sys.exit(0)
if text.count(ANCHOR) != 2 or text.count("location SUBFOLDER {") != 2:
    sys.exit(f"{path}: expected two server blocks with Selkies at SUBFOLDER and a 50x error page")
text = text.replace("SUBFOLDER", PREFIX)
open(path, "w", encoding="utf-8").write(text.replace(ANCHOR, BLOCK + ANCHOR))
