"""Exception bot web service (Project 3, Step 3.4).

  POST /mm/slash    Mattermost /exception command (form-encoded, checked with the command token)
  POST /mm/dialog   the request form was submitted
  POST /mm/action   an approver clicked Approve or Deny
  GET  /request     where Santa's block page sends people (shows the ready-made /exception command)
  GET  /dashboard   open exceptions by type, age and owner, plus renewal counts
A background job runs every TICK_SECONDS: activates merged grants, reminds, and expires.
`python app.py tick` runs it once by hand.
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import sys
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs

import yaml
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

from clients import Deploy, GitHub, HRDirectory, Mattermost, Tickets, WaiverFile
from service import ExceptionService

HERE = Path(__file__).resolve().parent
DATA = Path(os.environ.get("DATA_DIR", "/data"))
DATA.mkdir(parents=True, exist_ok=True)
CHAT_URL = os.environ.get("MM_PUBLIC_URL", "http://chat.lumen.test:8065")


def build() -> ExceptionService:
    env = os.environ.get
    return ExceptionService(
        yaml.safe_load((HERE / "types.yaml").read_text()), DATA / "exceptions.sqlite",
        mm=Mattermost(env("MM_URL", "http://mattermost:8065"), env("MM_BOT_TOKEN", "")),
        gh=GitHub(env("GITHUB_REPO", ""), env("GITHUB_TOKEN", "")),
        deploy=Deploy(env("DEPLOY_DIR", "/deploy"), env("GITHUB_TOKEN", "")),
        hr=HRDirectory(env("HR_URL", "http://hr:8100")),
        waivers=WaiverFile(env("WAIVER_FILE", "/waivers/waivers.json")),
        tickets=Tickets(DATA / "tickets.jsonl"),
        secret=env("BOT_SECRET", ""), bot_url=env("BOT_URL", "http://exceptions:8200"),
        security_approvers=[a.strip() for a in env("SECURITY_APPROVERS", "").split(",") if a.strip()],
        slash_token=env("MM_SLASH_TOKEN", ""), audit_path=DATA / "audit.jsonl")


SVC = build()
app = FastAPI(title="Lumen exception bot", docs_url=None, redoc_url=None, openapi_url=None)

PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title>
<style>
:root{{--ink:#1d1d1f;--muted:#5f6368;--line:#e3e3e8;--bg:#f6f6f8;--card:#fff;--accent:#5b3fd6;--on:#fff}}
@media (prefers-color-scheme:dark){{:root{{--ink:#ececf1;--muted:#a4a4ad;--line:#34343b;--bg:#141417;--card:#1e1e23;--accent:#9d8cff;--on:#141417}}}}
body{{margin:0;background:var(--bg);color:var(--ink);font:16px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif}}
main{{max-width:{width}px;margin:0 auto;padding:40px 16px 56px}} h1{{font-size:26px;margin:0 0 8px}}
.muted{{color:var(--muted)}} .card{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px 20px;margin:16px 0}}
code,pre{{font:14px ui-monospace,Menlo,monospace;word-break:break-all}} pre{{white-space:pre-wrap;word-break:break-all;margin:0}}
button,.btn{{font:inherit;font-weight:600;background:var(--accent);color:var(--on);border:0;border-radius:8px;padding:10px 16px;cursor:pointer;text-decoration:none;display:inline-block}}
table{{border-collapse:collapse;width:100%;font-size:14px}} th,td{{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line)}}
th{{color:var(--muted);font-weight:600}} .wrap{{overflow-x:auto}} .stats{{display:flex;gap:12px;flex-wrap:wrap}}
.stat{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 16px;min-width:120px}}
.stat b{{display:block;font-size:24px}}
</style></head><body><main>{body}</main></body></html>"""


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/mm/slash")
async def slash(request: Request):
    raw = await request.body()
    ctype = request.headers.get("content-type", "")
    if "json" in ctype:
        form = {k: str(v) for k, v in json.loads(raw or b"{}").items()}
    else:
        form = {k: v[0] for k, v in parse_qs(raw.decode()).items()}
    # Header form (newer Mattermost): "Authorization: Token <token>"
    auth = request.headers.get("authorization", "")
    if not form.get("token") and auth.lower().startswith("token "):
        form["token"] = auth[6:].strip()
    got, want = form.get("token", ""), SVC.slash_token
    if got != want:  # log enough to debug, never the token itself
        fp = lambda t: hashlib.sha256(t.encode()).hexdigest()[:8] if t else "-"
        print(json.dumps({"slash_token_mismatch": {"content_type": ctype, "fields": sorted(form),
              "auth_header": bool(auth), "got_len": len(got), "got_fp": fp(got),
              "want_len": len(want), "want_fp": fp(want)}}), flush=True)
    return SVC.slash(form)


@app.post("/mm/dialog")
async def dialog(request: Request):
    return SVC.submit(await request.json())


@app.post("/mm/action")
async def action(request: Request):
    return SVC.action(await request.json())


@app.get("/request", response_class=HTMLResponse)
def request_page(sha: str = "", machine: str = "", user: str = "", serial: str = "", problems: str = "", app: str = ""):
    """Santa's block page sends sha/machine/user; the posture gate's page sends serial/problems/app."""
    checks = [p for p in problems.split(",") if p in SVC.cfg["posture_checks"]]
    if sha:
        cmd = f"/exception binary {sha} {machine}".strip()
        title, intro = "Request access to a blocked app", ("Santa blocked an app on this Mac because it isn't on "
                                                           "Lumen's approved list.")
    elif checks:
        cmd = "\n".join(f"/exception waiver {c} {serial}" for c in checks)
        title, intro = "Request a temporary posture waiver", (f"Your laptop is failing {', '.join(checks)}, so "
                                                              f"{app or 'an app'} is blocked. Fixing it is better; "
                                                              "if you can't yet, ask for a short waiver.")
    else:
        cmd = "/exception"
        title, intro = "Request a security exception", "Open the form in chat and choose what you need."
    body = f"""<h1>{html.escape(title)}</h1>
<p class="muted">{html.escape(intro)} You can ask for a temporary exception: it needs an approver in chat,
and it's removed automatically when it ends.</p>
<div class="card"><p><b>1.</b> Copy this command{"s (one per check)" if "\n" in cmd else ""}:</p><pre id="c">{html.escape(cmd)}</pre>
<p><button onclick="navigator.clipboard.writeText(document.getElementById('c').textContent);this.textContent='Copied'">Copy command</button></p>
<p><b>2.</b> Open Lumen chat, paste it into any channel and press Enter. A short form opens with the app and Mac already filled in.</p>
<p><a class="btn" href="{html.escape(CHAT_URL)}">Open Lumen chat</a></p></div>
<p class="muted">Device: <code>{html.escape(machine or serial or "unknown")}</code>
{f'&middot; App fingerprint (SHA-256): <code>{html.escape(sha)}</code>' if sha else ''}</p>"""
    return PAGE.format(title="Request access", width=680, body=body)


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    d = SVC.dashboard()
    labels = {k: v["label"] for k, v in SVC.cfg["types"].items()}

    def rows(items, cols):
        out = "".join("<tr>" + "".join(f"<td>{html.escape(str(r.get(c) if r.get(c) is not None else ''))}</td>"
                                       for c in cols) + "</tr>" for r in items)
        return out or f'<tr><td colspan="{len(cols)}" class="muted">None</td></tr>'

    cols = ["id", "type", "requester_email", "status", "age_hours", "expires_at", "renewals", "approver_email"]
    head = "".join(f"<th>{h}</th>" for h in ["ID", "Type", "Owner", "Status", "Age (h)", "Expires", "Renewals", "Approver"])
    stats = "".join(f'<div class="stat"><span class="muted">{html.escape(labels.get(k, k))}</span><b>{v}</b></div>'
                    for k, v in d["by_type"].items())
    body = f"""<h1>Security exceptions</h1><p class="muted">Every exception has an approver and an end date.
Renewals show how often the same thing is requested again: a signal that a rule or a tool needs fixing.</p>
<div class="stats">{stats}<div class="stat"><span class="muted">Open</span><b>{len(d['open'])}</b></div>
<div class="stat"><span class="muted">Renewals (all time)</span><b>{d['renewals']}</b></div>
<div class="stat"><span class="muted">Denied</span><b>{d['denied']}</b></div>
<div class="stat"><span class="muted">Total requests</span><b>{d['total']}</b></div></div>
<h2>Open</h2><div class="wrap"><table><tr>{head}</tr>{rows(d['open'], cols)}</table></div>
<h2>Recently closed</h2><div class="wrap"><table><tr>{head}</tr>{rows(d['closed'], cols)}</table></div>"""
    return PAGE.format(title="Exceptions", width=1100, body=body)


def worker():
    while True:
        time.sleep(int(os.environ.get("TICK_SECONDS", "60")))
        try:
            SVC.tick()
        except Exception as e:  # noqa: BLE001
            print(f"tick error: {e}", flush=True)


threading.Thread(target=worker, daemon=True).start()

if __name__ == "__main__" and sys.argv[1:] == ["tick"]:
    print(SVC.tick())
