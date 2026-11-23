#!/usr/bin/env python3
"""Write alert.md listing today's new races that match config/alerts.json (nothing is written if none match)."""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
cfg = json.loads((ROOT / "config" / "alerts.json").read_text(encoding="utf-8"))
out = ROOT / "alert.md"
out.unlink(missing_ok=True)
if not cfg.get("enabled", True):
    sys.exit(0)
new = json.loads((ROOT / "data" / "new_today.json").read_text(encoding="utf-8"))
today = dt.date.today().isoformat()


def open_reg(r: dict) -> bool:
    if r.get("reg_closed") or r.get("sold_out"):
        return False
    return not (r.get("reg_close_date") and r["reg_close_date"] < today)


def keep(r: dict) -> bool:
    if cfg.get("regions") and r["region"] not in cfg["regions"]:
        return False
    if cfg.get("countries") and r["country"] not in cfg["countries"]:
        return False
    if cfg.get("distances") and not set(cfg["distances"]) & set(r.get("distances", [])):
        return False
    if cfg.get("only_open_registration") and not open_reg(r):
        return False
    if cfg.get("only_high_demand") and not r.get("popularity_flag"):
        return False
    if not cfg.get("include_trail", True) and r.get("surface") == "Trail":
        return False
    return True


hits = sorted((r for r in new if keep(r)), key=lambda r: r["race_date"])
if not hits:
    print("No new races match the alert rules today.")
    sys.exit(0)

lines = [f"{len(hits)} new race{'s' if len(hits) != 1 else ''} matched your alert rules today.\n",
         "| Date | Race | Where | Distances | Cost | Registration |", "|---|---|---|---|---|---|"]
for r in hits:
    name = r["name"] + (f"<br><sub>{r['name_local']}</sub>" if r.get("name_local") else "")
    cost = (f"C${r['cost_cad']:,.0f} ({r['cost_original']})" if r.get("cost_cad") else "Check site")
    reg = f"closes {r['reg_close_date']}" if r.get("reg_close_date") else "dates not listed"
    where = ", ".join(x for x in [r.get("city"), r["country"]] if x)
    lines.append(f"| {r['race_date']} | [{name}]({r['registration_url']}) | {where} | {', '.join(r.get('distances', []))} | {cost} | {reg} |")
lines.append("\nChange what triggers these alerts in `config/alerts.json`.")
out.write_text("\n".join(lines), encoding="utf-8")
print(f"{len(hits)} matching new races written to alert.md")
