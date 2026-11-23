"""Remember every race edition seen, and project next year's edition when a race has passed
and no new date has been announced ("Expected – date TBC")."""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HISTORY = ROOT / "data" / "history.json"
MAX_GAP_DAYS = 800          # a race not held for ~2 years is treated as discontinued
MATCH_WINDOW_DAYS = 75      # an announced race this close to the projected date replaces it
KEEP_FIELDS = ("name", "name_local", "region", "country", "city", "distances", "surface",
               "registration_url", "aims_certified", "popularity_flag", "popularity_reason")


def series_key(r: dict) -> str:
    """Same race in different years -> same key (years, edition numbers and punctuation removed)."""
    s = (r.get("name_local") or r.get("name") or "").lower()
    s = re.sub(r"20\d\d|'\d\d", "", s)
    s = re.sub(r"第\s*[\d一二三四五六七八九十百]+\s*[屆届回]|제\s*\d+\s*회|\b\d+(st|nd|rd|th)\b|\bno\.?\s*\d+\b", "", s)
    s = re.sub(r"[【\[(（].*?[】\])）]", "", s)            # bracketed notes like 【早割】 or (autumn)
    s = re.sub(r"[\s\W_]+", "", s)
    return f"{r.get('country', '')}|{s}"


def strip_year(name: str | None) -> str | None:
    if not name:
        return name
    n = re.sub(r"\s*\b20\d\d\b\s*", " ", name)
    n = re.sub(r"^(?:\d+(?:st|nd|rd|th)\s+)", "", n.strip())
    n = re.sub(r"第\s*[\d一二三四五六七八九十百]+\s*[屆届回]\s*|제\s*\d+\s*회\s*", "", n)
    return re.sub(r"\s{2,}", " ", n).strip(" -–")


def load() -> dict:
    try:
        return json.loads(HISTORY.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save(h: dict) -> None:
    HISTORY.write_text(json.dumps(h, ensure_ascii=False, indent=0, sort_keys=True), encoding="utf-8")


def record(h: dict, races: list[dict]) -> None:
    for r in races:
        if r.get("expected") or r.get("date_tbd") or not r.get("race_date"):
            continue
        k = series_key(r)
        if not k.split("|", 1)[1]:
            continue
        e = h.setdefault(k, {"dates": []})
        if r["race_date"] not in e["dates"]:
            e["dates"] = sorted(set(e["dates"] + [r["race_date"]]))
        if r["race_date"] >= max(e["dates"]):  # keep the newest edition's details
            for f in KEEP_FIELDS:
                if r.get(f) not in (None, "", []):
                    e[f] = r[f]
            e["sources"] = r.get("sources", [])


def add_past_editions(h: dict, rows: list[dict]) -> None:
    """Rows from directories: {key fields..., 'race_date': past date}."""
    record(h, rows)


def project(h: dict, races: list[dict], today: dt.date) -> list[dict]:
    """Expected next editions for series whose last date has passed and nothing newer is listed."""
    upcoming: dict[str, list[str]] = {}
    for r in races:
        if not r.get("expected"):
            upcoming.setdefault(series_key(r), []).append(r["race_date"])
    out = []
    for k, e in h.items():
        if not e.get("dates") or not e.get("name"):
            continue
        last = dt.date.fromisoformat(e["dates"][-1])
        if last >= today or (today - last).days > MAX_GAP_DAYS:
            continue
        nxt = last
        while nxt <= today:
            nxt += dt.timedelta(days=364)   # 52 weeks keeps the weekday
        if any(abs((dt.date.fromisoformat(d) - nxt).days) <= MATCH_WINDOW_DAYS or d > e["dates"][-1]
               for d in upcoming.get(k, [])):
            continue  # the real date is already listed
        held = ", ".join(dt.date.fromisoformat(d).strftime("%-d %b %Y") for d in e["dates"][-3:])
        r = {f: e.get(f) for f in KEEP_FIELDS}
        r["name"] = strip_year(r.get("name"))
        r["name_local"] = strip_year(r.get("name_local"))
        lead = "Held in " + held if len(e["dates"]) > 1 else "Last held " + held
        r.update(
            race_date=nxt.isoformat(), date_tbd=True, expected=True, last_held=e["dates"][-1],
            distances=e.get("distances") or [], sources=e.get("sources") or [], source_urls=[],
            cost_original=None, cost_currency=None, cost_cad=None, cost_cad_max=None,
            reg_open_date=None, reg_close_date=None, reg_state_raw=None, reg_closed=False,
            entry_type=None, sold_out=False,
            note=f"{lead}. Next date not announced yet – if it runs again, expect it around "
                 f"{nxt.strftime('%B %Y')}.",
        )
        if r.get("name_local") and r["name"] == r["name_local"]:
            r["name_local"] = None
        out.append(r)
    return out
