"""A tiny local request logger: receives HR webhooks, checks the signature, flags duplicates.

Stands in for the JML engine (Step 3.2) so you can SEE what HR sends. It uses the same
verify() the engine will use. Nothing leaves your machine (unlike online request bins).
"""
import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

from signing import verify

SECRET = os.environ.get("HR_WEBHOOK_SECRET", "")
seen: set[str] = set()


class Logger(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        ok, why = verify(SECRET, body, self.headers.get("X-HR-Signature", ""))
        event_id = self.headers.get("X-HR-Event-Id", "")
        duplicate = event_id in seen
        if ok:
            seen.add(event_id)
        print("=" * 72, flush=True)
        print(f"{self.command} {self.path}", flush=True)
        for h in ("X-HR-Event-Id", "X-HR-Event-Type", "X-HR-Signature"):
            print(f"{h}: {self.headers.get(h)}", flush=True)
        verdict = "VALID" if ok else f"INVALID ({why})"
        print(f"Signature: {verdict}" + ("   DUPLICATE: already processed, would be ignored" if duplicate else ""),
              flush=True)
        print(json.dumps(json.loads(body or b"{}"), indent=2), flush=True)
        self.send_response(200 if ok else 401)
        self.end_headers()

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    print("Request logger listening on :8199", flush=True)
    HTTPServer(("0.0.0.0", 8199), Logger).serve_forever()
