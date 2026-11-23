"""AIMS calendar – marks races as AIMS certified, and adds certified races in our regions that no local source lists."""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

from common import blank_race, parse_en_date

URL = "https://aims-worldrunning.org/calendar.html"
COUNTRIES = {
    "TPE": ("Taiwan", "East Asia"), "TWN": ("Taiwan", "East Asia"), "JPN": ("Japan", "East Asia"),
    "KOR": ("South Korea", "East Asia"), "HKG": ("Hong Kong", "East Asia"), "MAC": ("Macau", "East Asia"),
    "CHN": ("China", "East Asia"), "MAS": ("Malaysia", "Southeast Asia"), "MYS": ("Malaysia", "Southeast Asia"),
    "SGP": ("Singapore", "Southeast Asia"), "SIN": ("Singapore", "Southeast Asia"), "THA": ("Thailand", "Southeast Asia"),
    "INA": ("Indonesia", "Southeast Asia"), "IDN": ("Indonesia", "Southeast Asia"), "PHI": ("Philippines", "Southeast Asia"),
    "PHL": ("Philippines", "Southeast Asia"), "VIE": ("Vietnam", "Southeast Asia"), "VNM": ("Vietnam", "Southeast Asia"),
    "CAM": ("Cambodia", "Southeast Asia"), "KHM": ("Cambodia", "Southeast Asia"), "LAO": ("Laos", "Southeast Asia"),
    "MYA": ("Myanmar", "Southeast Asia"), "BRU": ("Brunei", "Southeast Asia"), "CAN": ("Canada", "Canada"),
}
CODES = {"M": "Marathon", "H": "Half Marathon", "U": "Ultra"}


def parse(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    out, month = [], None
    for el in soup.select("h3.calendar-month-header, div.calendar-item"):
        if el.name == "h3":
            month = el.get_text(strip=True)
            continue
        if not month:
            continue
        day_el = el.select_one(".calendar-date")
        a = el.select_one(".calendar-race-name > a")
        cc = el.select_one("a.calendar-country-code")
        if not (day_el and a and cc):
            continue
        code = cc.get_text(strip=True)
        if code not in COUNTRIES:
            continue
        day = re.match(r"\s*(\d{1,2})", day_el.get_text())
        d = parse_en_date(f"{day.group(1)} {month}") if day else None
        if not d:
            continue
        sup = el.select_one(".calendar-supinfo").get_text(" ", strip=True) if el.select_one(".calendar-supinfo") else ""
        letters = re.findall(r"\b([MHRUC])\b", sup.replace(code, ""))
        dists = [CODES[x] for x in letters if x in CODES]
        country, region = COUNTRIES[code]
        note = None
        for flag in ("postponed", "provisional", "Rescheduled", "cancelled"):
            if flag.lower() in sup.lower():
                note = "AIMS: " + sup.split(code)[-1].strip(" ,")
        url = a.get("href")
        out.append(blank_race(
            name=a.get_text(strip=True), region=region, country=country, race_date=d.isoformat(),
            distances=[x for x in ["Half Marathon", "Marathon", "Ultra"] if x in dists], aims_certified=True,
            registration_url=url, detail_url=None, source_urls=[url], sources=["AIMS"], note=note,
        ))
    return out
