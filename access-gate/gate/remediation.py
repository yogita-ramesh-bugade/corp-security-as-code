"""The page people see when the posture gate denies access (Project 2, Step 2.5).

For every problem it shows three things, in plain language:
  what's wrong  -  how to fix it (steps for THIS person's operating system)  -  why it matters
plus a "Check again" button and a "Request an exception" link (Project 3's bot).
All wording lives in checks.yaml, so it can be improved without touching code.
"""
from __future__ import annotations

import html
from urllib.parse import urlencode

APP_NAMES = {"wiki": "the Wiki", "admin-console": "the Admin Console"}


def os_family(platform: str) -> str:
    if platform == "darwin":
        return "darwin"
    if platform == "windows":
        return "windows"
    return "linux"


def _card(n: int, title: str, what: str, steps: list[str], why: str) -> str:
    items = "".join(f"<li>{html.escape(s)}</li>" for s in steps)
    return f"""
<section class="card" aria-labelledby="t{n}">
  <h2 id="t{n}"><span class="num">{n}</span>{html.escape(title)}</h2>
  <p class="what"><b>What's wrong:</b> {html.escape(what)}</p>
  <p class="label">How to fix it:</p>
  <ol>{items}</ol>
  <p class="why"><b>Why it matters:</b> {html.escape(why)}</p>
</section>"""


def render(content: dict, decision: dict, app_name: str, email: str, exception_url: str,
           next_path: str, rechecking: bool) -> str:
    device = decision.get("device") or {}
    serial = device.get("serial", "unknown")
    family = os_family(device.get("platform", ""))
    checks, reasons = content["checks"], content["reasons"]

    cards, problems = [], []
    for reason in sorted(decision.get("reasons") or []):
        if reason == "device_unhealthy":
            continue  # shown as one card per failing check below
        r = reasons.get(reason, {"title": reason, "what": "", "why": "", "steps": []})
        cards.append((r["title"], r["what"].format(email=email), r["steps"], r["why"]))
        problems.append(reason)
    for check in sorted(decision.get("remediation") or []):
        c = checks.get(check, {})
        steps = (c.get("steps") or {}).get(family) or (c.get("steps") or {}).get("darwin") or []
        cards.append((c.get("title", check), c.get("what", ""), steps, c.get("why", "")))
        problems.append(check)

    body = "".join(_card(i + 1, *card) for i, card in enumerate(cards))
    n = len(cards)
    app_label = APP_NAMES.get(app_name, app_name)
    heading = (f"One thing to fix before you can open {app_label}" if n == 1
               else f"{n} things to fix before you can open {app_label}")
    query = urlencode({"app": app_name, "serial": serial, "user": email, "problems": ",".join(problems)})
    exception_link = f"{exception_url}{'&' if '?' in exception_url else '?'}{query}"
    refresh = '<meta http-equiv="refresh" content="20">' if rechecking else ""
    status = ('<p class="checking" role="status">Checking your laptop again. This page refreshes by itself '
              'every 20 seconds; it can take up to 2 minutes.</p>' if rechecking else "")

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
{refresh}<title>Access blocked: {html.escape(app_label)}</title>
<style>
  :root {{ --ink:#1d1d1f; --muted:#5f6368; --line:#e3e3e8; --bg:#f6f6f8; --card:#fff; --accent:#5b3fd6; --on-accent:#fff; --warn:#b42318; }}
  @media (prefers-color-scheme: dark) {{ :root {{ --ink:#ececf1; --muted:#a4a4ad; --line:#34343b; --bg:#141417; --card:#1e1e23; --accent:#9d8cff; --on-accent:#141417; --warn:#ff8a80; }} }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--ink); font:16px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif; }}
  main {{ max-width:680px; margin:0 auto; padding:40px 16px 56px; }}
  .eyebrow {{ color:var(--warn); font-weight:600; font-size:14px; letter-spacing:.02em; margin:0 0 6px; }}
  h1 {{ font-size:28px; line-height:1.25; margin:0 0 8px; }}
  .lede {{ color:var(--muted); margin:0 0 28px; }}
  .card {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:20px 22px; margin:0 0 16px; }}
  h2 {{ font-size:19px; margin:0 0 10px; display:flex; gap:10px; align-items:center; }}
  .num {{ flex:none; width:26px; height:26px; border-radius:50%; background:var(--accent); color:var(--on-accent); font-size:14px;
          display:inline-flex; align-items:center; justify-content:center; }}
  .label {{ font-weight:600; margin:14px 0 4px; }}
  ol {{ margin:0 0 4px; padding-left:22px; }} li {{ margin:6px 0; }}
  .why {{ color:var(--muted); font-size:15px; margin:14px 0 0; border-top:1px solid var(--line); padding-top:12px; }}
  .actions {{ display:flex; flex-wrap:wrap; gap:12px; align-items:center; margin:28px 0 8px; }}
  button {{ font:inherit; font-weight:600; color:var(--on-accent); background:var(--accent); border:0; border-radius:8px; padding:12px 20px; cursor:pointer; }}
  button:focus-visible, a:focus-visible {{ outline:3px solid var(--accent); outline-offset:2px; }}
  a {{ color:var(--accent); }}
  .checking {{ background:var(--card); border:1px solid var(--line); border-radius:8px; padding:12px 14px; }}
  .meta {{ color:var(--muted); font-size:13px; margin-top:28px; }}
</style></head>
<body><main>
  <p class="eyebrow">Access blocked</p>
  <h1>{html.escape(heading)}</h1>
  <p class="lede">Your sign-in worked. Lumen also checks that the laptop is safe before opening company apps.
  Follow the steps below; most fixes take a couple of minutes.</p>
  {status}
  {body}
  <div class="actions">
    <form method="post" action="/_gate/recheck"><input type="hidden" name="next" value="{html.escape(next_path)}">
      <button type="submit">I've fixed it, check again</button></form>
    <a href="{html.escape(exception_link)}">Can't fix it? Request an exception</a>
  </div>
  <p class="meta">Signed in as {html.escape(email)} &middot; Laptop serial {html.escape(serial)} &middot;
  Access level {decision.get("level", 0)} of {decision.get("required_level", "?")} needed.
  Quote the serial if you contact IT.</p>
</main></body></html>"""
