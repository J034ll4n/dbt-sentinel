# -*- coding: utf-8 -*-
import json
import os

import engine
import ui

ROOT = os.path.dirname(os.path.abspath(__file__))
cfg = json.load(open(os.path.join(ROOT, "config.json"), encoding="utf-8"))
os.makedirs(cfg["output_path"], exist_ok=True)
s = engine.run(cfg)
html = ui.render(s)
path = os.path.join(cfg["output_path"], "index.html")
with open(path, "w", encoding="utf-8") as f:
    f.write(html)
with open(os.path.join(cfg["output_path"], "session.json"), "w", encoding="utf-8") as f:
    json.dump(s, f, ensure_ascii=False, indent=2)

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
print("nodes", len((s.get("lineage") or {}).get("nodes") or []))
