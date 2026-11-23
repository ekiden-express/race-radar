"""JomRun – Malaysia and the rest of Southeast Asia (plus its Hong Kong/Taiwan/Japan listings).

Fees are shown only as images behind a login, so JomRun races never get a CAD price.
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

from common import blank_race, norm_distances, parse_en_date

BASE = "https://www.jomrun.com"
EVENTS_URL = BASE + "/events"
WANTED = {
    "Malaysia": "Southeast Asia", "Singapore": "Southeast Asia", "Thailand": "Southeast Asia",
    "Indonesia": "Southeast Asia", "Philippines": "Southeast Asia", "Brunei": "Southeast Asia",
    "Cambodia": "Southeast Asia", "Myanmar": "Southeast Asia", "Vietnam": "Southeast Asia",
    "Hong Kong": "East Asia", "Japan": "East Asia",
}  # Taiwan is left to 運動筆記, which covers it far better
SKIP_NAMES = re.compile(r"\b(walk|funwalk|virtual|merchandise only)\b", re.I)


def parse_locations(html: str) -> dict[str, tuple[str, str]]:
    """location_id -> (country, state) from the location chooser on /events."""
    out: dict[str, tuple[str, str]] = {}
    country = None
    for m in re.finditer(
        r"location_id=(\d+)\"\s+onclick=\"gtag\('event',\s*'([^']+)',\s*\{'event_category'\s*:\s*'(country|state)'", html
    ):
        lid, label, kind = m.groups()
        if kind == "country":
            country = label.strip()
            out.setdefault(lid, (country, label.strip()))
        elif country:
            out[lid] = (country, label.strip())
    # a country that has a single location (Singapore, Japan) is listed as a state only
    for lid, (c, s) in list(out.items()):
        if s in WANTED and c != s and c not in WANTED:
            out[lid] = (s, s)
    return out


def parse_cards(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    seen, out = set(), []
    for card in soup.select(".events_count"):
        a = card.select_one("h3 a") or card.find_parent("a")
        if not a:
            continue
        url = a.get("href", "")
        if "/event/" not in url or url in seen:
            continue
        seen.add(url)
        name = a.get_text(strip=True).replace("®", "").replace("Powered by JomRun", "").replace("Powered By JomRun", "").strip(" -–")
        date_li = card.select_one(".icon-calendar3")
        dtxt = date_li.parent.get_text(" ", strip=True) if date_li else ""
        d = parse_en_date(re.sub(r"(\d+)(st|nd|rd|th)", r"\1", dtxt.split("(")[0]))
        out.append({"url": url, "name": name, "race_date": d.isoformat() if d else None})
    return out


def parse_detail(html: str) -> dict:
    soup = BeautifulSoup(html, "lxml")
    for s in soup(["script", "style"]):
        s.decompose()
    lines = [l for l in soup.get_text("\n", strip=True).split("\n") if l.strip()]
    upd: dict = {}
    try:
        i = lines.index("Event Info:")
        d = parse_en_date(lines[i + 1])
        if d:
            upd["race_date"] = d.isoformat()
        # date, time, venue
        venue = lines[i + 3] if i + 3 < len(lines) and lines[i + 3] not in ("Add to my calendar", "Buy Ticket") else None
        if venue and not re.match(r"^\d{1,2}:\d\d", venue):
            upd["venue"] = venue
    except ValueError:
        pass
    text = "\n".join(lines)
    m = re.search(r"REGISTRATION ENDS AT\s*\n?\s*([^\n]+)", text, re.I)
    if m:
        d = parse_en_date(m.group(1).split("(")[0])
        if d:
            upd["reg_close_date"] = d.isoformat()
    kms = re.findall(r"(\d+(?:\.\d+)?)\s?KM\s+(?:Fun|Competitive|Run|Race|Ultra|Trail|Challenge|Category|Elite|Open)", text, re.I)
    if kms:
        raw = ", ".join(sorted(set(k + "KM" for k in kms), key=lambda x: float(x[:-2])))
        upd["distances_raw"] = raw
        upd["distances"] = norm_distances(raw)
    if re.search(r"sold\s*out|fully\s*booked", text, re.I):
        upd["sold_out"] = True
    return upd


def build(card: dict, country: str, state: str) -> dict | None:
    if SKIP_NAMES.search(card["name"]) or not card["race_date"]:
        return None
    region = WANTED.get(country)
    if not region:
        return None
    return blank_race(
        name=card["name"], region=region, country=country, city=state if state != country else None,
        race_date=card["race_date"], distances=norm_distances(card["name"]),
        registration_url=card["url"], detail_url=card["url"], source_urls=[card["url"]], sources=["JomRun"],
        note="JomRun shows fees only after you log in – check site.",
    )
