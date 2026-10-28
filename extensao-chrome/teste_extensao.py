"""Teste da extensão: sobe um servidor local com redirect, cookies, POST, gzip, binário, iframe de outra
origem e popup, carrega a extensão num Chromium do Playwright, grava e confere o HAR.

Uso: uv run python extensao-chrome/teste_extensao.py"""
import gzip
import json
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright

EXT = str(Path(__file__).resolve().parent)
PNG = bytes(range(256)) * 4


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, status, body=b"", ctype="text/html", headers=()):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        for k, v in headers:
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        port = self.server.server_port
        if self.path == "/":
            html = f"""<html><body>
<img src="/img.png">
<iframe src="http://localhost:{port}/frame"></iframe>
<script>
fetch('/api', {{method: 'POST', headers: {{'Content-Type': 'application/json'}}, body: JSON.stringify({{'usuário': 'x'}})}})
  .then(() => {{ window.open('/popup'); setTimeout(() => location.href = '/redir', 1000); }});
</script></body></html>""".encode()
            self.send(200, html, "text/html; charset=utf-8", headers=[("Set-Cookie", "a=1; Path=/"), ("Set-Cookie", "b=2; HttpOnly")])
        elif self.path == "/redir":
            self.send(302, b"", headers=[("Location", "/final"), ("Set-Cookie", "c=3")])
        elif self.path == "/final":
            self.send(200, "fim ção".encode(), "text/plain; charset=utf-8")
        elif self.path == "/img.png":
            self.send(200, PNG, "image/png")
        elif self.path == "/frame":
            self.send(200, b"<script>fetch('/frame-data')</script>")
        elif self.path == "/frame-data":
            self.send(200, b'{"frame": true}', "application/json")
        elif self.path == "/popup":
            self.send(200, b"popup")
        elif self.path == "/favicon.ico":
            self.send(404, b"nf")
        else:
            self.send(404, b"nf")

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        self.send(200, gzip.compress(b'{"eco": ' + body + b"}"), "application/json", [("Content-Encoding", "gzip")])


server = ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=server.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{server.server_port}"

with sync_playwright() as p, tempfile.TemporaryDirectory() as profile:
    ctx = p.chromium.launch_persistent_context(
        profile, channel="chromium", headless=True,
        args=[f"--disable-extensions-except={EXT}", f"--load-extension={EXT}"],
    )
    sw = ctx.service_workers[0] if ctx.service_workers else ctx.wait_for_event("serviceworker")
    page = ctx.pages[0]
    page.goto("about:blank")
    sw.evaluate("chrome.tabs.query({}).then(t => start(t[0].id))")
    page.wait_for_timeout(500)
    page.goto(base + "/")
    page.wait_for_url("**/final")
    page.wait_for_timeout(1500)
    har = sw.evaluate("stop()")
    downloads = sw.evaluate("new Promise(r => setTimeout(() => chrome.downloads.search({}).then(r), 1000))")
    ctx.close()

entries = har["log"]["entries"]
for e in entries:
    c = e["response"]["content"]
    print(e["request"]["method"], e["response"]["status"], e["request"]["url"], c.get("encoding", ""), c["size"], repr(c["text"][:40]))
by = {e["request"]["url"].replace(base, "").replace(f"http://localhost:{server.server_port}", "LH"): e for e in entries}

root = by["/"]["response"]
assert [c["name"] for c in root["cookies"]] == ["a", "b"], root["cookies"]
assert by["/redir"]["response"]["status"] == 302 and by["/redir"]["response"]["redirectUrl"] == "/final"
assert by["/redir"]["response"]["cookies"] == [{"name": "c", "value": "3"}]
assert {"name": "a", "value": "1"} in by["/final"]["request"]["cookies"], by["/final"]["request"]["cookies"]
assert by["/final"]["response"]["content"]["text"] == "fim ção"
api = by["/api"]
assert json.loads(api["request"]["postData"]["text"]) == {"usuário": "x"}
assert json.loads(api["response"]["content"]["text"]) == {"eco": {"usuário": "x"}}
assert by["/img.png"]["response"]["content"]["encoding"] == "base64"
assert by["/img.png"]["response"]["content"]["size"] == len(PNG)
assert "LH/frame-data" in by, "iframe cross-site não gravado"
assert "/popup" in by, "popup não gravado"
assert not any(h["name"].startswith(":") for e in entries for h in e["request"]["headers"])
print("downloads:", [(d["filename"], d["state"], d.get("error")) for d in downloads])
print("OK", len(entries), "entries")
