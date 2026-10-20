"""Route /agents/ on the Selkies web server to the desktop viewer.

Applied at image build to the baseimage's nginx template
(/defaults/default.conf), so the viewer shares the desktop's origin and its
Cloudflare Access protection. Fails the build if the template changes shape.
"""
import sys

BLOCK = """  location SUBFOLDERagents/ {
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
