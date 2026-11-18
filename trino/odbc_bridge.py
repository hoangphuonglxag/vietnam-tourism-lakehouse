"""
Lightweight HTTP bridge translating Starburst ODBC 3.x JSON-wrapped /v1/statement
requests ({"query": "...", "preparedStatements": {...}}) into plain-text SQL
for Trino OSS (/v1/statement).
"""

from __future__ import annotations

import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from urllib.parse import quote


LISTEN_HOST = os.getenv("BRIDGE_LISTEN_HOST", "0.0.0.0")
LISTEN_PORT = int(os.getenv("BRIDGE_LISTEN_PORT", "8082"))
TRINO_HOST = os.getenv("TRINO_UPSTREAM_HOST", "trino")
TRINO_PORT = int(os.getenv("TRINO_UPSTREAM_PORT", "8080"))

HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "content-length",
}


def _unwrap_statement_payload(raw_body: bytes, headers: dict[str, str]) -> tuple[bytes, dict[str, str]]:
    """If body is JSON {"query": "..."}, extract raw SQL and map preparedStatements."""
    text = raw_body.decode("utf-8", errors="replace").lstrip()
    if not text.startswith("{"):
        return raw_body, headers

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return raw_body, headers

    if not isinstance(payload, dict) or "query" not in payload:
        return raw_body, headers

    sql = str(payload["query"])
    updated_headers = dict(headers)
    updated_headers["Content-Type"] = "text/plain; charset=utf-8"

    prepared = payload.get("preparedStatements")
    if isinstance(prepared, dict) and prepared:
        pairs = [f"{quote(str(k), safe='')}={quote(str(v), safe='')}" for k, v in prepared.items()]
        existing = updated_headers.get("X-Trino-Prepared-Statement")
        joined = ", ".join(pairs)
        updated_headers["X-Trino-Prepared-Statement"] = f"{existing}, {joined}" if existing else joined

    return sql.encode("utf-8"), updated_headers


class TrinoBridgeHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args) -> None:
        # Keep container logs concise
        pass

    def _forward(self, method: str) -> None:
        content_length = int(self.headers.get("Content-Length", "0") or "0")
        raw_body = self.rfile.read(content_length) if content_length > 0 else b""

        forward_headers: dict[str, str] = {}
        for k, v in self.headers.items():
            if k.lower() in HOP_BY_HOP_HEADERS:
                continue
            # Avoid compressed upstream responses so bridge can forward raw JSON cleanly
            if k.lower() == "accept-encoding":
                continue
            forward_headers[k] = v

        if method == "POST" and self.path.startswith("/v1/statement"):
            raw_body, forward_headers = _unwrap_statement_payload(raw_body, forward_headers)

        if raw_body:
            forward_headers["Content-Length"] = str(len(raw_body))

        conn = http.client.HTTPConnection(TRINO_HOST, TRINO_PORT, timeout=300)
        try:
            conn.request(method, self.path, body=raw_body if raw_body else None, headers=forward_headers)
            resp = conn.getresponse()
            resp_body = resp.read()

            self.send_response(resp.status, resp.reason)
            for k, v in resp.getheaders():
                if k.lower() in HOP_BY_HOP_HEADERS:
                    continue
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(resp_body)))
            self.end_headers()
            if resp_body and method != "HEAD":
                self.wfile.write(resp_body)
        except Exception as exc:
            err = json.dumps({"error": str(exc)}).encode("utf-8")
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(err)))
            self.end_headers()
            self.wfile.write(err)
        finally:
            conn.close()

    def do_GET(self) -> None:
        self._forward("GET")

    def do_POST(self) -> None:
        self._forward("POST")

    def do_PUT(self) -> None:
        self._forward("PUT")

    def do_DELETE(self) -> None:
        self._forward("DELETE")

    def do_HEAD(self) -> None:
        self._forward("HEAD")


def main() -> None:
    server = ThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), TrinoBridgeHandler)
    print(f"trino-odbc-bridge listening on {LISTEN_HOST}:{LISTEN_PORT} -> {TRINO_HOST}:{TRINO_PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
