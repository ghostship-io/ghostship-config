"""Make the desktop viewer the one entry point of the Selkies web server.

Applied at image build to the baseimage's nginx template
(/defaults/default.conf), so the viewer shares the desktop's origin and its
Cloudflare Access protection. Fails the build if the template changes shape.

- /agents/ proxies to the viewer, whose Desktop mode frames Selkies at /.
- A top-level page load of / (Sec-Fetch-Dest: document) redirects to the
  viewer; frames, health checks and clients without the header still get
  Selkies, so its URL and saved settings stay unchanged.
- Redirects stay relative. nginx otherwise builds them from its own listen
  port, e.g. /agents -> http://desktop.ghostship.io:3000/agents/.
"""
import sys

BLOCK = """  absolute_redirect       off;
  location = SUBFOLDER {
    if ($http_sec_fetch_dest = "document") {
      return 302 SUBFOLDERagents/;
    }
    alias /usr/share/selkies/web/;
    index  index.html;
  }
  location SUBFOLDERagents/ {
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
if "location SUBFOLDERagents/" in text:
    sys.exit(0)
if text.count(ANCHOR) != 2:
    sys.exit(f"{path}: expected two server blocks ending in the 50x error page")
open(path, "w", encoding="utf-8").write(text.replace(ANCHOR, BLOCK + ANCHOR))
