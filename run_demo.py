# -*- coding: utf-8 -*-
import json
import os

import engine
import ui

ROOT = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(ROOT, "config.json"), encoding="utf-8-sig") as f:
    cfg = json.load(f)
for key in ("workspace_path", "output_path", "snapshots_path", "base_project_path"):
    p = cfg.get(key, "")
    if p and isinstance(p, str) and not os.path.isabs(p):
        cfg[key] = os.path.abspath(os.path.join(ROOT, p))
os.makedirs(cfg["output_path"], exist_ok=True)
s = engine.run(cfg)
html = ui.render(s)
path = os.path.join(cfg["output_path"], "index.html")
with open(path, "w", encoding="utf-8") as f:
    f.write(html)
with open(os.path.join(cfg["output_path"], "session.json"), "w", encoding="utf-8") as f:
    json.dump(s, f, ensure_ascii=False, indent=2)
with open(os.path.join(cfg["output_path"], "roteiro.md"), "w", encoding="utf-8") as f:
    f.write(s.get("order_markdown") or "")

print("card", s["card_id"])
print("msg", s.get("message"))
print("summary", s["summary"])
print("checklist:")
for c in s["checklist"]:
    if c["status"] == "IGUAL":
        continue
    summary = (c.get("add_summary") or "")[:80]
    print(f"  {c['status']:10} {c['name']:28} +{c.get('add_count', 0)}  {summary}")
print("HTML:", path)
print("roteiro:", os.path.join(cfg["output_path"], "roteiro.md"))
print("nodes", len((s.get("lineage") or {}).get("nodes") or []))
