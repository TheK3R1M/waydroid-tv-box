#!/usr/bin/env python3
"""Mock of the tv-remote API for UI tests: serves the page, fakes /state /channels, records every POST."""
import http.server, json, sys, time
PAGE = sys.argv[1]
LOG = []
ST = {"vol": 85, "muted": False, "max": 150, "normal": 85, "app": "TV", "split": None, "err": None,
      "via_router": "--router" in sys.argv, "you": "mock", "last": {"who": "x", "what": "y", "ago": 5}}
CH = ["TRT 1 (1440p)", "ATV (720p)", "Show TV", "Kanal D (1080p)", "Star TV (720p)", "NOW", "TV8 (1080p)"] * 4


class H(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def send(self, code, body=b"", ct="text/plain"):
        self.send_response(code); self.send_header("Content-Type", ct); self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)

    def do_GET(self):
        p = self.path.split("?")[0]
        if p == "/":
            return self.send(200, open(PAGE, "rb").read(), "text/html; charset=utf-8")
        if p == "/state":
            return self.send(200, json.dumps(ST).encode(), "application/json")
        if p == "/channels":
            return self.send(200, json.dumps(CH).encode(), "application/json")
        if p == "/__log":
            return self.send(200, json.dumps(LOG).encode(), "application/json")
        if p == "/__reset":
            LOG.clear(); return self.send(200, b"ok")
        self.send(404)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(n).decode("utf-8", "ignore") if n else ""
        LOG.append({"t": round(time.time(), 2), "path": self.path, "body": body, "dev": self.headers.get("X-TV-Device")})
        if self.path.startswith("/vol"):
            return self.send(200, json.dumps(ST).encode(), "application/json")
        self.send(200)

    def log_message(self, *a):
        pass


http.server.ThreadingHTTPServer(("127.0.0.1", int(sys.argv[2])), H).serve_forever()
