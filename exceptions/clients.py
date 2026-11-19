"""Connections from the exception bot to Mattermost, GitHub, HR and the waiver file.
Each has a fake twin in test_exceptions.py."""
from __future__ import annotations

import base64
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

import httpx


class Mattermost:
    def __init__(self, url: str, bot_token: str):
        self.url, self.h = url.rstrip("/"), {"Authorization": f"Bearer {bot_token}"}
        self._me = None

    def _r(self, method, path, **kw):
        r = httpx.request(method, f"{self.url}/api/v4{path}", headers=self.h, timeout=10, **kw)
        r.raise_for_status()
        return r.json() if r.content else {}

    def bot_id(self):
        if not self._me:
            self._me = self._r("GET", "/users/me")["id"]
        return self._me

    def user(self, user_id):
        return self._r("GET", f"/users/{user_id}")

    def user_by_email(self, email):
        try:
            return self._r("GET", f"/users/email/{email}")
        except httpx.HTTPStatusError:
            return None

    def dm(self, user_id, message, attachments=None):
        channel = self._r("POST", "/channels/direct", json=[self.bot_id(), user_id])["id"]
        props = {"attachments": attachments} if attachments else {}
        return self._r("POST", "/posts", json={"channel_id": channel, "message": message, "props": props})["id"]

    def open_dialog(self, trigger_id, url, dialog):
        self._r("POST", "/actions/dialogs/open", json={"trigger_id": trigger_id, "url": url, "dialog": dialog})


class GitHub:
    """Opens and merges pull requests that change one file (contents + pulls API)."""

    def __init__(self, repo: str, token: str):
        self.repo = repo
        self.h = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                  "X-GitHub-Api-Version": "2022-11-28"}

    def _r(self, method, path, ok=(200, 201), **kw):
        r = httpx.request(method, f"https://api.github.com/repos/{self.repo}{path}", headers=self.h, timeout=20, **kw)
        if r.status_code not in ok:
            raise RuntimeError(f"GitHub {method} {path}: {r.status_code} {r.text[:200]}")
        return r

    def read(self, path, ref="main"):
        r = self._r("GET", f"/contents/{path}", ok=(200, 404), params={"ref": ref})
        if r.status_code == 404:
            return None, None
        j = r.json()
        return base64.b64decode(j["content"]).decode(), j["sha"]

    def change_file_pr(self, path, content, branch, title, body) -> int:
        base = self._r("GET", "/git/ref/heads/main").json()["object"]["sha"]
        self._r("POST", "/git/refs", json={"ref": f"refs/heads/{branch}", "sha": base})
        _, sha = self.read(path, ref=branch)
        payload = {"message": title, "content": base64.b64encode(content.encode()).decode(), "branch": branch}
        if sha:
            payload["sha"] = sha
        self._r("PUT", f"/contents/{path}", json=payload)
        return self._r("POST", "/pulls", json={"title": title, "head": branch, "base": "main", "body": body}).json()["number"]

    def try_merge(self, number) -> bool:
        r = self._r("PUT", f"/pulls/{number}/merge", ok=(200, 405, 409, 422), json={"merge_method": "squash"})
        if r.status_code == 200:
            self._r("DELETE", f"/git/refs/heads/{self._r('GET', f'/pulls/{number}').json()['head']['ref']}",
                    ok=(204, 422))
            return True
        return False

    def is_merged(self, number) -> bool:
        return self._r("GET", f"/pulls/{number}").json().get("merged", False)


class Deploy:
    """The copy of the repo that Moroz reads (main only). Pulled after every merge."""

    def __init__(self, path: str, token: str):
        self.path, self.token = path, token

    def pull(self) -> str:
        if not self.path or not Path(self.path, ".git").exists():
            return "no deploy clone configured"
        auth = base64.b64encode(f"x-access-token:{self.token}".encode()).decode()
        r = subprocess.run(["git", "-C", self.path, "-c", f"http.extraHeader=Authorization: Basic {auth}",
                            "pull", "--ff-only", "-q"], capture_output=True, text=True, timeout=60)
        return "pulled" if r.returncode == 0 else f"pull failed: {r.stderr.strip()[:200]}"


class HRDirectory:
    def __init__(self, url):
        self.url = url.rstrip("/")

    def by_email(self, email):
        for e in httpx.get(f"{self.url}/employees", params={"status": "active"}, timeout=10).json():
            if e["email"].lower() == email.lower():
                return e
        return None


class WaiverFile:
    """{"waivers": [...]} that OPA loads (opa run --watch), written atomically."""

    def __init__(self, path):
        self.path = Path(path)

    def load(self):
        return json.loads(self.path.read_text())["waivers"] if self.path.exists() else []

    def save(self, waivers):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent)
        with os.fdopen(fd, "w") as f:
            json.dump({"waivers": waivers}, f, indent=1)
        os.chmod(tmp, 0o644)
        os.replace(tmp, self.path)

    def add(self, entry):
        self.save([w for w in self.load() if w["id"] != entry["id"]] + [entry])

    def remove(self, exc_id):
        self.save([w for w in self.load() if w["id"] != exc_id])


class Tickets:
    def __init__(self, path):
        self.path = Path(path)

    def file(self, title, **fields):
        with open(self.path, "a") as f:
            f.write(json.dumps({"title": title, **fields, "time": time.strftime("%Y-%m-%dT%H:%M:%SZ")}) + "\n")
