"""A small Sigma evaluator for CI: does a rule match these log samples? (Project 4, Step 4.6)

Elasticsearch isn't available in CI, so tests run each rule against sample logs in Python.
It reads the same pipeline.yml the real conversion uses (field mapping + dataset conditions),
so a wrong mapping fails here too. It supports the subset of Sigma our rules use:
equals (case-sensitive, like our keyword fields), lists (OR), the modifiers contains,
startswith, endswith, lt, lte, gt, gte, conditions with and/or/not/parentheses, and value_count
and event_count correlations with group-by and timespan.
Conversion to Lucene is still done by pySigma; this only checks the logic.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent


class Pipeline:
    def __init__(self, path: Path = HERE / "pipeline.yml"):
        doc = yaml.safe_load(Path(path).read_text())
        self.mapping, self.datasets = {}, []
        for t in doc["transformations"]:
            if t["type"] == "field_name_mapping":
                self.mapping.update(t["mapping"])
            elif t["type"] == "add_condition":
                rc = t["rule_conditions"][0]
                self.datasets.append(({k: v for k, v in rc.items() if k != "type"}, t["conditions"]))

    def field(self, name: str) -> str:
        return self.mapping.get(name, name)

    def extra_conditions(self, logsource: dict) -> dict:
        out = {}
        for want, cond in self.datasets:
            if all(logsource.get(k) == v for k, v in want.items()):
                out.update(cond)
        return out


def get(event: dict, path: str):
    """event["a"]["b"] or event["a.b"]: logs may be nested or flat."""
    if path in event:
        return event[path]
    cur = event
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _one(actual, expected, mod) -> bool:
    if actual is None:
        return False
    if isinstance(expected, bool) or isinstance(actual, bool):
        return actual is expected if isinstance(expected, bool) else str(actual).lower() == str(expected).lower()
    if mod in ("lt", "lte", "gt", "gte"):
        try:
            a, e = float(actual), float(expected)
        except (TypeError, ValueError):
            return False
        return {"lt": a < e, "lte": a <= e, "gt": a > e, "gte": a >= e}[mod]
    a, e = str(actual), str(expected)
    return {None: a == e, "contains": e in a, "startswith": a.startswith(e), "endswith": a.endswith(e)}[mod]


def match_item(event: dict, key: str, expected, pipe: Pipeline) -> bool:
    field, *mods = key.split("|")
    mod = mods[0] if mods else None
    actual = get(event, pipe.field(field))
    actuals = actual if isinstance(actual, list) else [actual]
    wanted = expected if isinstance(expected, list) else [expected]
    return any(_one(a, w, mod) for a in actuals for w in wanted)


def match_rule(rule: dict, event: dict, pipe: Pipeline) -> bool:
    for field, value in pipe.extra_conditions(rule["logsource"]).items():
        if get(event, field) != value:
            return False
    det = rule["detection"]
    results = {name: all(match_item(event, k, v, pipe) for k, v in sel.items())
               for name, sel in det.items() if name != "condition"}
    cond = det["condition"]
    if not re.fullmatch(r"[\w\s()]+", cond):
        raise ValueError(f"unsupported condition: {cond}")
    tokens = re.findall(r"\(|\)|\w+", cond)
    expr = " ".join(t if t in ("and", "or", "not", "(", ")") else repr(results[t]) for t in tokens)
    return bool(eval(expr, {"__builtins__": {}}))  # only True/False/and/or/not/() reach eval


def _time(event) -> datetime:
    return datetime.fromisoformat(str(get(event, "@timestamp")).replace("Z", "+00:00"))


def _span(text: str) -> timedelta:
    n, unit = int(text[:-1]), text[-1]
    return {"s": timedelta(seconds=n), "m": timedelta(minutes=n), "h": timedelta(hours=n), "d": timedelta(days=n)}[unit]


def correlation_fires(corr: dict, base: dict, events: list[dict], pipe: Pipeline) -> list[tuple]:
    """Groups (by group-by values) where the condition held inside some window of `timespan`."""
    c = corr["correlation"]
    hits = sorted((e for e in events if match_rule(base, e, pipe)), key=_time)
    span, cond = _span(c["timespan"]), c["condition"]
    groups: dict[tuple, list] = {}
    for e in hits:
        groups.setdefault(tuple(get(e, pipe.field(g)) for g in c.get("group-by", [])), []).append(e)
    fired = []
    for key, evs in groups.items():
        for i, start in enumerate(evs):
            window = [e for e in evs[i:] if _time(e) - _time(start) <= span]
            if c["type"] == "value_count":
                n = len({str(get(e, pipe.field(cond["field"]))) for e in window})
            elif c["type"] == "event_count":
                n = len(window)
            else:
                raise ValueError(f"unsupported correlation type {c['type']}")
            op = next(k for k in ("gte", "gt", "lte", "lt", "eq") if k in cond)
            if {"gte": n >= cond[op], "gt": n > cond[op], "lte": n <= cond[op], "lt": n < cond[op], "eq": n == cond[op]}[op]:
                fired.append(key)
                break
    return fired


def load_rules(rules_dir: Path = HERE / "rules") -> dict[str, list[dict]]:
    """file stem -> the YAML documents in it (a correlation file has the base rule + correlation)."""
    return {p.stem: [d for d in yaml.safe_load_all(p.read_text()) if d] for p in sorted(Path(rules_dir).glob("*.yml"))}
