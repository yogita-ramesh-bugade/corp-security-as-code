"""Convert the Sigma rules and load them into Kibana as detection rules (Project 4, Step 4.6).

    python -m detections.deploy --dry-run       # print every converted query, change nothing
    python -m detections.deploy                 # create or update the rules in Kibana

Plain rules are converted by pySigma (Lucene backend + detections/pipeline.yml) and become
Kibana "query" rules. The Lucene backend can't express correlation rules, so for those this
script converts the base rule the same way and builds a Kibana "threshold" rule from the
correlation's group-by, timespan and condition (value_count -> threshold cardinality). The
ES|QL version pySigma can produce is printed too, for comparison.

Settings: KIBANA_URL (http://localhost:5601), ELASTIC_USER (elastic), ELASTIC_PASSWORD.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import httpx
import yaml
from sigma.backends.elasticsearch import ESQLBackend, LuceneBackend
from sigma.collection import SigmaCollection
from sigma.processing.pipeline import ProcessingPipeline

HERE = Path(__file__).resolve().parent
INDEX = ["lumen-logs-*"]
RISK = {"informational": 21, "low": 21, "medium": 47, "high": 73, "critical": 99}


def pipeline() -> ProcessingPipeline:
    return ProcessingPipeline.from_yaml((HERE / "pipeline.yml").read_text())


def lucene(rule_yaml: str) -> str:
    [q] = LuceneBackend(pipeline()).convert(SigmaCollection.from_yaml(rule_yaml))
    return q


def _span_minutes(text: str) -> int:
    n, unit = int(text[:-1]), text[-1]
    return n * {"m": 1, "h": 60, "d": 1440}[unit]


def build_rules(rules_dir: Path = HERE / "rules") -> list[dict]:
    pipe_map = next(t["mapping"] for t in yaml.safe_load((HERE / "pipeline.yml").read_text())["transformations"]
                    if t["type"] == "field_name_mapping")
    out = []
    for path in sorted(Path(rules_dir).glob("*.yml")):
        text = path.read_text()
        docs = [d for d in yaml.safe_load_all(text) if d]
        base_by_name = {d["name"]: d for d in docs if d.get("name") and "detection" in d}
        for d in docs:
            common = {"rule_id": d["id"], "name": d["title"], "description": " ".join(d["description"].split()),
                      "severity": "critical" if d["level"] == "critical" else d["level"], "risk_score": RISK[d["level"]],
                      "index": INDEX, "interval": "1m", "enabled": True, "language": "lucene",
                      "tags": ["lumen", "sigma"] + [t for t in d.get("tags", [])],
                      "false_positives": d.get("falsepositives", []), "author": [d.get("author", "")],
                      "license": "Lab", "max_signals": 100}
            if "correlation" in d:
                c = d["correlation"]
                base = base_by_name[c["rules"][0]]
                base_q = lucene(yaml.safe_dump(base, sort_keys=False))
                cond = c["condition"]
                if c["type"] != "value_count" or "gte" not in cond:
                    raise ValueError(f"{path.name}: only value_count with gte is mapped to a threshold rule")
                minutes = _span_minutes(c["timespan"])
                out.append({**common, "type": "threshold", "query": base_q, "from": f"now-{minutes}m",
                            "threshold": {"field": [pipe_map.get(g, g) for g in c.get("group-by", [])], "value": 1,
                                          "cardinality": [{"field": pipe_map.get(cond["field"], cond["field"]),
                                                           "value": cond["gte"]}]},
                            "_source_file": path.name})
            elif d.get("name") and any(d["name"] in (x.get("correlation") or {}).get("rules", []) for x in docs):
                continue  # a base rule only used by a correlation: no alert of its own
            else:
                out.append({**common, "type": "query", "query": lucene(yaml.safe_dump(d, sort_keys=False)),
                            "from": "now-6m", "_source_file": path.name})
    return out


def esql_versions(rules_dir: Path = HERE / "rules") -> dict[str, list[str]]:
    out = {}
    for path in sorted(Path(rules_dir).glob("*.yml")):
        try:
            out[path.name] = ESQLBackend(pipeline()).convert(SigmaCollection.from_yaml(path.read_text()))
        except Exception as e:  # noqa: BLE001
            out[path.name] = [f"(not convertible: {e})"]
    return out


class Kibana:
    def __init__(self, url=None, user=None, password=None):
        self.url = (url or os.environ.get("KIBANA_URL", "http://localhost:5601")).rstrip("/")
        self.auth = (user or os.environ.get("ELASTIC_USER", "elastic"), password or os.environ["ELASTIC_PASSWORD"])
        self.h = {"kbn-xsrf": "true", "Content-Type": "application/json", "elastic-api-version": "2023-10-31"}

    def _r(self, method, path, **kw):
        return httpx.request(method, f"{self.url}{path}", auth=self.auth, headers=self.h, timeout=30, **kw)

    def upsert_rule(self, rule: dict) -> str:
        body = {k: v for k, v in rule.items() if not k.startswith("_")}
        r = self._r("POST", "/api/detection_engine/rules", json=body)
        verb = "created"
        if r.status_code == 409:  # already there: replace it with the current version
            r, verb = self._r("PUT", "/api/detection_engine/rules", json=body), "updated"
        if r.status_code >= 400:
            raise SystemExit(f"Kibana refused '{rule['name']}': HTTP {r.status_code} {r.text[:600]}")
        return verb

    def data_view(self) -> str:
        r = self._r("POST", "/api/data_views/data_view", json={"data_view": {
            "id": "lumen-logs", "title": "lumen-logs-*", "name": "Lumen lab logs", "timeFieldName": "@timestamp"}})
        return "created" if r.status_code == 200 else "exists" if r.status_code in (400, 409) else f"HTTP {r.status_code}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    rules = build_rules()
    if a.dry_run:
        for r in rules:
            extra = f"  threshold={json.dumps(r['threshold'])}  window={r['from']}" if r["type"] == "threshold" else ""
            print(f"[{r['type']:9}] {r['name']}\n   {r['query']}{extra}\n")
        print("ES|QL versions (for comparison):")
        for f, qs in esql_versions().items():
            for q in qs:
                print(f"   {f}: {' '.join(q.split())}")
        return 0
    kb = Kibana()
    print(f"data view lumen-logs-*: {kb.data_view()}")
    for r in rules:
        print(f"{kb.upsert_rule(r):8} {r['type']:9} {r['name']}")
    print(f"\n{len(rules)} rules loaded. Kibana > Security > Rules > Detection rules (SIEM).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
