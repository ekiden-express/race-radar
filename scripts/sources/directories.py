"""International race directories, used to fill gaps where local calendars are thin.

- World's Marathons: race pages carry the latest edition's date and country. Upcoming dates become
  races; past dates go into history so next year's edition shows as "Expected – date TBC".
- Marathon Index: ~430 well-known races with a next date that may be an estimate ("Date TBC").
- config/watch_urls.json: any race page from those sites (or Ahotu) you want tracked.

Race pages are cached for weeks, so each run opens only a few new ones.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

from bs4 import BeautifulSoup

from common import ROOT, TODAY, blank_race, norm_distances

CACHE = ROOT / "data" / "cache" / "directories.json"
WATCH = ROOT / "config" / "watch_urls.json"
PARSER_VERSION = 1
REFRESH_DAYS = 21

COUNTRIES = {  # ISO-2 code or name -> (country, region)
    "TW": ("Taiwan", "East Asia"), "JP": ("Japan", "East Asia"), "KR": ("South Korea", "East Asia"),
    "HK": ("Hong Kong", "East Asia"), "MO": ("Macau", "East Asia"), "CN": ("China", "East Asia"),
    "MY": ("Malaysia", "Southeast Asia"), "SG": ("Singapore", "Southeast Asia"), "TH": ("Thailand", "Southeast Asia"),
    "ID": ("Indonesia", "Southeast Asia"), "PH": ("Philippines", "Southeast Asia"), "VN": ("Vietnam", "Southeast Asia"),
    "KH": ("Cambodia", "Southeast Asia"), "LA": ("Laos", "Southeast Asia"), "MM": ("Myanmar", "Southeast Asia"),
    "BN": ("Brunei", "Southeast Asia"), "TL": ("Timor-Leste", "Southeast Asia"), "CA": ("Canada", "Canada"),
}
BY_NAME = {v[0].lower(): v for v in COUNTRIES.values()} | {"korea": COUNTRIES["KR"], "viet nam": COUNTRIES["VN"],
                                                            "lao pdr": COUNTRIES["LA"], "republic of korea": COUNTRIES["KR"]}

# Slug words that point to a race in our regions (World's Marathons slugs usually name the city).
SLUG_HINTS = re.compile(r"(?<![a-z])(" + "|".join([
    # Southeast Asia
    "laos", "lao", "vientiane", "luang-prabang", "vang-vieng", "pakse", "cambodia", "angkor", "siem-reap", "phnom-penh",
    "sihanoukville", "kampot", "vietnam", "hanoi", "ha-noi", "ho-chi-minh", "saigon", "hcmc", "da-nang", "danang", "halong",
    "ha-long", "hue", "hoi-an", "nha-trang", "da-lat", "dalat", "phu-quoc", "quy-nhon", "sapa", "moc-chau", "mekong",
    "thailand", "bangkok", "phuket", "chiang-mai", "chiang-rai", "pattaya", "krabi", "khon-kaen", "hua-hin", "koh-samui",
    "buriram", "korat", "udon", "amazing-thailand", "malaysia", "kuala-lumpur", "penang", "george-town", "langkawi",
    "johor", "kota-kinabalu", "sabah", "sarawak", "kuching", "melaka", "malacca", "ipoh", "putrajaya", "borneo",
    "singapore", "indonesia", "bali", "jakarta", "borobudur", "yogyakarta", "bandung", "surabaya", "lombok", "bintan",
    "batam", "maybank", "philippines", "manila", "cebu", "boracay", "davao", "clark", "subic", "palawan", "iloilo",
    "baguio", "myanmar", "yangon", "bagan", "mandalay", "brunei", "timor", "dili",
    # East Asia
    "taiwan", "taipei", "kaohsiung", "taichung", "tainan", "hualien", "taitung", "kenting", "sun-moon-lake", "yilan",
    "japan", "tokyo", "osaka", "kyoto", "nagoya", "kobe", "fukuoka", "sapporo", "hokkaido", "okinawa", "naha", "nagano",
    "hiroshima", "yokohama", "chiba", "sendai", "kanazawa", "shizuoka", "beppu", "oita", "ehime", "matsuyama", "kumamoto",
    "kagoshima", "ishigaki", "niigata", "fuji", "kagawa", "marugame", "nara", "korea", "seoul", "busan", "jeju", "gyeongju",
    "daegu", "chuncheon", "incheon", "hong-kong", "macau", "macao", "china", "beijing", "shanghai", "xiamen", "guangzhou",
    "shenzhen", "chengdu", "hangzhou", "wuxi", "suzhou", "lanzhou", "chongqing", "great-wall",
    # Canada
    "canada", "vancouver", "victoria", "whistler", "kelowna", "squamish", "calgary", "edmonton", "banff", "canmore",
    "jasper", "saskatoon", "regina", "winnipeg", "toronto", "ottawa", "montreal", "quebec", "niagara", "hamilton",
    "mississauga", "waterloo", "london-ontario", "halifax", "fredericton", "moncton", "st-johns", "charlottetown",
    "yukon", "whitehorse", "yellowknife", "okanagan", "bmo", "scotiabank", "beneva", "tamarack",
]) + r")(?![a-z])")


def load_cache() -> dict:
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_cache(c: dict) -> None:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(c, ensure_ascii=False, indent=0), encoding="utf-8")


def watch_urls() -> list[str]:
    try:
        return [u for u in json.loads(WATCH.read_text(encoding="utf-8")).get("urls", []) if u.startswith("http")]
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _events(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    out = []
    for sc in soup.find_all("script", type="application/ld+json"):
        try:
            j = json.loads(sc.string or "")
        except json.JSONDecodeError:
            continue
        items = j if isinstance(j, list) else j.get("@graph", [j])
        for it in items:
            if isinstance(it, dict) and "Event" in str(it.get("@type", "")) and it.get("startDate"):
                out.append(it)
    title = soup.find("h1")
    return out, (title.get_text(" ", strip=True) if title else "")


def parse_page(html: str, url: str) -> dict | None:
    """One race page -> {name, date, country, region, city, distances} (latest edition), or None."""
    events, h1 = _events(html)
    if not events:
        return None
    ev = sorted(events, key=lambda e: e["startDate"])[-1]
    addr = ((ev.get("location") or {}).get("address") or {})
    if isinstance(addr, str):
        addr = {"addressCountry": addr}
    cc = addr.get("addressCountry") or ""
    if isinstance(cc, dict):
        cc = cc.get("name") or cc.get("identifier") or ""
    cc = str(cc).strip()
    place = COUNTRIES.get(cc.upper()) or BY_NAME.get(cc.lower())
    if not place:
        return {"skip": True, "country_code": cc}
    name = (ev.get("name") or h1 or "").strip()
    text = " ".join(str(e.get("name", "")) for e in events) + " " + (ev.get("description") or "")[:400]
    return {
        "name": name, "race_date": ev["startDate"][:10], "country": place[0], "region": place[1],
        "city": addr.get("addressLocality"), "distances": norm_distances(text + " " + name), "url": url,
    }


def wm_race_urls(sitemap_xml: str) -> list[str]:
    urls = re.findall(r"<loc>\s*(https://(?:www\.)?worldsmarathons\.com/marathon/[^<\s]+)\s*</loc>", sitemap_xml)
    return sorted({u for u in urls if SLUG_HINTS.search(u.rsplit("/", 1)[-1].lower())})


def mindex_race_urls(sitemap_xml: str) -> list[str]:
    return sorted(set(re.findall(r"<loc>(https://marathon-index\.com/races/[a-z0-9\-]+/)</loc>", sitemap_xml)))


def to_rows(info: dict, source: str, unconfirmed: bool) -> tuple[dict | None, dict | None]:
    """-> (upcoming race or None, past edition for history or None)."""
    if not info or info.get("skip") or not info.get("race_date"):
        return None, None
    if re.search(r"virtual|online", info.get("name", ""), re.I):
        return None, None
    r = blank_race(name=info["name"], region=info["region"], country=info["country"], city=info.get("city"),
                   race_date=info["race_date"], distances=info.get("distances") or [],
                   registration_url=info["url"], source_urls=[info["url"]], sources=[source])
    if info["race_date"] < TODAY.isoformat():
        return None, r
    if unconfirmed:
        r["date_unconfirmed"] = True
        r["note"] = f"Date from {source}; it may be an estimate – confirm on the official site."
    return r, None


def is_fresh(hit: dict | None) -> bool:
    return bool(hit and hit.get("v") == PARSER_VERSION
                and (TODAY - dt.date.fromisoformat(hit["fetched"])).days < REFRESH_DAYS)


def run(f, budget: int = 120) -> tuple[list[dict], list[dict], dict]:
    """Returns (upcoming races, past editions, stats)."""
    cache = load_cache()
    stats = {"opened": 0, "cached": 0, "in_regions": 0}
    todo: list[tuple[str, str, bool]] = []  # (url, source, unconfirmed)
    try:
        idx = f.get("https://www.worldsmarathons.com/index-sitemap-en.xml")
        for sm in re.findall(r"<loc>([^<]+)</loc>", idx):
            if "marathon" in sm.lower() or "race" in sm.lower() or "event" in sm.lower():
                todo += [(u, "World's Marathons", False) for u in wm_race_urls(f.get(sm.strip()))]
    except Exception as e:  # noqa: BLE001
        stats["wm_error"] = str(e)[:200]
    try:
        todo += [(u, "Marathon Index", True) for u in mindex_race_urls(f.get("https://marathon-index.com/sitemap-0.xml"))]
    except Exception as e:  # noqa: BLE001
        stats["mindex_error"] = str(e)[:200]
    for u in watch_urls():
        src = "World's Marathons" if "worldsmarathons" in u else "Marathon Index" if "marathon-index" in u else \
              "Ahotu" if "ahotu" in u else "Watched link"
        todo.insert(0, (u, src, "marathon-index" in u))
    stats["candidates"] = len(todo)

    upcoming, past = [], []
    seen = set()
    for url, source, unconfirmed in todo:
        if url in seen:
            continue
        seen.add(url)
        hit = cache.get(url)
        if not is_fresh(hit):
            if budget <= 0:
                if not hit:
                    continue
            else:
                budget -= 1
                try:
                    info = parse_page(f.get(url), url)
                    hit = cache[url] = {"fetched": TODAY.isoformat(), "v": PARSER_VERSION, "data": info}
                    stats["opened"] += 1
                except Exception:  # noqa: BLE001
                    if not hit:
                        continue
        else:
            stats["cached"] += 1
        info = hit.get("data")
        if info and not info.get("skip"):
            stats["in_regions"] += 1
        up, pa = to_rows(info, source, unconfirmed)
        if up:
            upcoming.append(up)
        if pa:
            past.append(pa)
    save_cache(cache)
    return upcoming, past, stats
