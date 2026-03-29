from mitmproxy import http

def request(flow: http.HTTPFlow) -> None:
    # Remove Origin headers to prevent CSWSH block
    if "Origin" in flow.request.headers:
        del flow.request.headers["Origin"]
    if "origin" in flow.request.headers:
        del flow.request.headers["origin"]
