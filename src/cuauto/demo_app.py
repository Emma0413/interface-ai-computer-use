from __future__ import annotations

import html
import os
import secrets
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import cast
from urllib.parse import parse_qs, urlsplit

MEMBERS = {"M1001": ("Avery Stone", "$1,245.67"), "M2002": ("Jordan Lake", "$88.10")}
SESSIONS: set[str] = set()


def page(title: str, body: str) -> bytes:
    return f"""<!doctype html><html><head><title>{html.escape(title)}</title>
<style>body{{font:16px serif;background:#eee}}table,.panel{{border:2px outset #bbb;background:#ddd;padding:14px}}
td{{padding:6px}}.error{{color:#900;font-weight:bold}}</style></head>
<body><table width="760"><tr><td><h1>First Federal LegacyCore</h1>{body}</td></tr></table></body></html>""".encode()


class Handler(BaseHTTPRequestHandler):
    server_version = "LegacyCore/1.0"

    def log_message(self, fmt: str, *args: object) -> None:
        print("demo", fmt % args)

    def _session(self) -> bool:
        cookie = SimpleCookie(self.headers.get("Cookie"))
        return "legacy_session" in cookie and cookie["legacy_session"].value in SESSIONS

    def _send(self, body: bytes, status: int = 200, cookie: str | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        if cookie:
            self.send_header("Set-Cookie", f"legacy_session={cookie}; HttpOnly; SameSite=Strict")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed, query = urlsplit(self.path), parse_qs(urlsplit(self.path).query)
        if parsed.path == "/":
            token = secrets.token_urlsafe(24)
            SESSIONS.add(token)
            self._send(
                page(
                    "Member Search",
                    """<h2>Member Search</h2><p>Search members</p>
<form method="post" action="/search"><label for="member">Member number</label>
<input id="member" name="member" maxlength="12"><button type="submit">Search</button></form>""",
                ),
                cookie=token,
            )
        elif parsed.path == "/member" and self._session():
            member = query.get("id", [""])[0]
            if member == "permission":
                self._send(page("Denied", '<p class="error">Permission denied</p>'), 403)
            elif member in MEMBERS:
                name, balance = MEMBERS[member]
                self._send(
                    page(
                        "Member Detail",
                        f"""<h2>Member record</h2><div class="panel">
<p>Member: {html.escape(name)}</p><table id="accounts"><tr><th>Account</th><th>Balance</th></tr>
<tr><td>Savings balance</td><td>{balance}</td></tr></table>
<form action="/review"><button type="submit">Begin address change</button></form></div>""",
                    )
                )
            else:
                self._send(page("Not found", '<p class="error">No member found</p>'))
        elif parsed.path == "/expire":
            self._send(
                page("Expired", '<p class="error">Session expired — authentication required</p>'),
                401,
            )
        elif parsed.path == "/error":
            self._send(page("Error", '<p class="error">Application error</p>'), 500)
        elif parsed.path == "/review" and self._session():
            self._send(page("Review", "<h2>Review change</h2><p>No change has been committed.</p>"))
        else:
            self._send(page("Not found", "<p>Missing page</p>"), 404)

    def do_POST(self) -> None:
        if self.path != "/search" or not self._session():
            self._send(
                page("Expired", '<p class="error">Session expired — authentication required</p>'),
                401,
            )
            return
        host, port = cast(tuple[str, int], self.server.server_address)[:2]
        expected_origin = f"http://{host}:{port}"
        if self.headers.get("Origin") not in {None, expected_origin}:
            self._send(page("Forbidden", "<p>Origin rejected</p>"), 403)
            return
        length = min(int(self.headers.get("Content-Length", "0")), 1024)
        member = parse_qs(self.rfile.read(length).decode()).get("member", [""])[0]
        if not member or len(member) > 12:
            self._send(
                page("Validation", '<p class="error">Validation error: invalid member number</p>')
            )
            return
        if member not in MEMBERS:
            self._send(
                page(
                    "Search results", '<h2>Search results</h2><p class="error">No member found</p>'
                )
            )
            return
        name, _ = MEMBERS[member]
        self._send(
            page(
                "Search results",
                f"""<h2>Search results</h2><table><tr><th>Member</th><th>Action</th></tr>
<tr><td>{html.escape(name)}</td><td><a href="/member?id={html.escape(member)}">Open member</a></td></tr></table>""",
            )
        )


def serve(host: str = "127.0.0.1", port: int = 8765) -> None:
    if host not in {"127.0.0.1", "localhost"} and os.environ.get("CUAUTO_UNSAFE_BIND") != "1":
        raise ValueError("demo binds to localhost unless CUAUTO_UNSAFE_BIND=1")
    ThreadingHTTPServer((host, port), Handler).serve_forever()
