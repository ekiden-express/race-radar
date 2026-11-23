#!/usr/bin/env python3
"""Global Race Radar – fetch, normalise, merge and write data/races.json.

Run:  python scripts/fetch_races.py            (normal daily run)
      SAVE_SNAPSHOTS=1 python scripts/fetch_races.py   (also save raw pages to data/snapshots/)
"""
from __future__ import annotations

import datetime as dt
import difflib
import json
import re
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "sources"))

import aims  # noqa: E402
import directories  # noqa: E402
import history  # noqa: E402
import biji  # noqa: E402
import jomrun  # noqa: E402
import roadrun  # noqa: E402
import runnet  # noqa: E402
from common import ROOT, TODAY, Fetcher, fmt_money, race_id  # noqa: E402

DATA = ROOT / "data" / "races.json"
CACHE = ROOT / "data" / "cache" / "details.json"
NEW_TODAY = ROOT / "data" / "new_today.json"
CONFIG = json.loads((ROOT / "config" / "sources.json").read_text(encoding="utf-8"))
MANUAL = ROOT / "config" / "manual_races.json"
NAMES = ROOT / "config" / "name_translations.json"
TRANS_CACHE = ROOT / "data" / "cache" / "translations.json"
MT_URL = "https://api.mymemory.translated.net/get"
MT_PER_RUN = 80
NON_LATIN = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af\uff01-\uff5e]")
FX_URL = "https://open.er-api.com/v6/latest/CAD"
CURRENCIES = ["TWD", "JPY", "KRW", "HKD", "MYR", "SGD", "THB", "IDR", "PHP", "VND", "CNY", "MOP", "BND", "KHR", "USD", "CAD"]
MAJORS = re.compile(r"^(?:\d{4}\s*)?(?:tokyo marathon|東京マラソン|東京馬拉松)(?:\s*\d{4})?$", re.I)  # World Marathon Majors in our regions
START = time.time()


def log(*a):
    print(f"[{time.time() - START:6.1f}s]", *a, flush=True)


def src_cfg(sid: str) -> dict:
    return next((s for s in CONFIG["sources"] if s["id"] == sid), {"enabled": False})


# ---------------------------------------------------------------- currency
def load_fx(f: Fetcher, previous: dict) -> dict:
    try:
        j = f.get_json(FX_URL)
        if j.get("result") != "success":
            raise RuntimeError(j.get("error-type", "unknown error"))
        rates = {c: j["rates"][c] for c in CURRENCIES if c in j["rates"]}
        date = dt.datetime.strptime(j["time_last_update_utc"][5:16], "%d %b %Y").date().isoformat()
        return {"date": date, "provider": "ExchangeRate-API (open.er-api.com)", "rates": rates, "stale": False}
    except Exception as e:  # noqa: BLE001
        log("FX failed, reusing previous rates:", e)
        fx = dict(previous or {})
        fx["stale"] = True
        return fx


def to_cad(amount: float | None, cur: str | None, fx: dict) -> float | None:
    if amount is None or not cur:
        return None
    rate = (fx.get("rates") or {}).get(cur)
    return round(amount / rate, 2) if rate else None  # rates are units of `cur` per 1 CAD


# ---------------------------------------------------------------- detail cache
def load_cache() -> dict:
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def cached_detail(cache: dict, url: str, fetch_fn, budget: list[int], version: int = 1) -> dict | None:
    hit = cache.get(url)
    if hit and hit.get("v", 1) == version and (TODAY - dt.date.fromisoformat(hit["fetched"])).days < CONFIG.get("detail_cache_days", 7):
        return hit["data"]
    if budget[0] <= 0 or time.time() - START > 12 * 60:
        return hit["data"] if hit else None
    budget[0] -= 1
    try:
        data = fetch_fn(url)
        cache[url] = {"fetched": TODAY.isoformat(), "v": version, "data": data}
        return data
    except Exception as e:  # noqa: BLE001
        log("  detail failed", url, e)
        return hit["data"] if hit else None


def worth_detail(r: dict) -> bool:
    """Only open detail pages for races you could still enter."""
    if r.get("reg_closed"):
        return False
    close = r.get("reg_close_date")
    return not (close and close < TODAY.isoformat())


# ---------------------------------------------------------------- sources
def run_biji(f: Fetcher, cache: dict) -> list[dict]:
    races = biji.parse_list(f.get(biji.LIST_URL, "biji_list"))
    budget = [src_cfg("biji").get("detail_pages_per_run", 80)]
    for r in races:
        if worth_detail(r):
            d = cached_detail(cache, r["detail_url"], lambda u, r=r: biji.parse_detail(f.get(u), r), budget, biji.PARSER_VERSION)
            if d:
                apply_detail(r, d)
    return races


def run_jomrun(f: Fetcher, cache: dict) -> list[dict]:
    locs = jomrun.parse_locations(f.get(jomrun.EVENTS_URL, "jomrun_events"))
    out, seen = [], set()
    for lid, (country, state) in sorted(locs.items(), key=lambda x: int(x[0])):
        if country not in jomrun.WANTED:
            continue
        url = f"{jomrun.BASE}/events/location?location_id={lid}"
        try:
            html = f.get(url)
        except Exception as e:  # noqa: BLE001
            log("  JomRun location failed", lid, e)
            continue
        if f"Events in {state}" not in html and f"Events in {country}" not in html:
            continue  # redirected to the generic page: no events here
        for card in jomrun.parse_cards(html):
            if card["url"] in seen:
                continue
            seen.add(card["url"])
            r = jomrun.build(card, country, state)
            if r:
                out.append(r)
    budget = [src_cfg("jomrun").get("detail_pages_per_run", 40)]
    for r in out:
        if r["race_date"] >= TODAY.isoformat():
            d = cached_detail(cache, r["detail_url"], lambda u: jomrun.parse_detail(f.get(u)), budget)
            if d:
                apply_detail(r, d)
    return out


def run_runnet(f: Fetcher, cache: dict) -> list[dict]:
    cfg = src_cfg("runnet")
    pages = cfg.get("pages_per_distance", 2)
    out = []
    for cls in runnet.DISTANCE_CLASSES:
        out += runnet.parse_results(f.get(runnet.SEARCH.format(cls=cls), f"runnet_{cls}"))
        for n in range(2, pages + 1):
            out += runnet.parse_results(f.get(runnet.PAGE.format(n=n)))
    uniq = {r["detail_url"]: r for r in out}
    return list(uniq.values())


def run_roadrun(f: Fetcher, cache: dict) -> list[dict]:
    out = roadrun.parse_list(f.get(roadrun.LIST_URL, "roadrun"))
    if TODAY.month >= 9:  # next year's calendar fills in from autumn
        nxt = TODAY.year + 1
        r = f.s.post(roadrun.LIST_URL, data={"syear_key": str(nxt)}, timeout=30)
        r.encoding = r.apparent_encoding
        out += roadrun.parse_list(r.text, year=nxt)
    return out


PAST_EDITIONS: list[dict] = []
DIRECTORY_STATS: dict = {}


def run_directories(f: Fetcher, cache: dict) -> list[dict]:
    up, past, stats = directories.run(f, budget=src_cfg("directories").get("pages_per_run", 120))
    PAST_EDITIONS.extend(past)
    DIRECTORY_STATS.update(stats)
    log("directories:", stats, f"upcoming {len(up)}, past editions {len(past)}")
    return up


SOURCES = {"directories": run_directories, "biji": run_biji, "jomrun": run_jomrun, "runnet": run_runnet, "roadrun": run_roadrun}


def apply_detail(r: dict, d: dict) -> None:
    for k, v in d.items():
        if v in (None, "", []):
            continue
        if k == "fee_hint":
            continue
        if k in ("cost_low", "cost_high"):
            r[k] = v
        elif k == "official_url":
            r.setdefault("official_url", v)
        else:
            r[k] = v
    if r.get("venue") and not r.get("city"):
        r["city"] = r["venue"]


# ---------------------------------------------------------------- merge
def norm_name(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"20\d\d|第\s*\d+\s*[屆届回]|\d+(st|nd|rd|th)|powered by jomrun|®", "", s)
    s = re.sub(r"[\s\W_]+", "", s)
    return s


def same_race(a: dict, b: dict) -> bool:
    if a["race_date"] != b["race_date"] or a["country"] != b["country"]:
        return False
    na, nb = norm_name(a["name"]), norm_name(b["name"])
    if not na or not nb:
        return False
    return na in nb or nb in na or difflib.SequenceMatcher(None, na, nb).ratio() >= 0.72


def merge_into(base: dict, other: dict) -> None:
    """`base` came from the higher-priority source."""
    for k, v in other.items():
        if k in ("sources", "source_urls"):
            base[k] = list(dict.fromkeys(base.get(k, []) + v))
        elif base.get(k) in (None, "", [], False) and v not in (None, "", [], False):
            base[k] = v


CITY_CJK = {
    "taipei": "臺北|台北", "new taipei": "新北", "kaohsiung": "高雄", "taichung": "臺中|台中", "tainan": "臺南|台南",
    "hsinchu": "新竹", "chiayi": "嘉義", "yilan": "宜蘭", "hualien": "花蓮", "taitung": "臺東|台東", "pingtung": "屏東",
    "kenting": "墾丁", "taoyuan": "桃園", "kinmen": "金門", "penghu": "澎湖", "zengwen": "曾文", "changhua": "彰化",
    "nantou": "南投", "miaoli": "苗栗", "yunlin": "雲林", "keelung": "基隆", "sun moon lake": "日月潭",
    "tokyo": "東京", "osaka": "大阪", "kyoto": "京都", "nagoya": "名古屋", "kobe": "神戸|神戶", "fukuoka": "福岡",
    "hokkaido": "北海道", "sapporo": "札幌", "okinawa": "沖縄|沖繩", "naha": "那覇", "hiroshima": "広島", "sendai": "仙台",
    "beppu": "別府", "oita": "大分", "ehime": "愛媛", "matsuyama": "松山", "marugame": "丸亀|丸龜", "kagawa": "香川",
    "shizuoka": "静岡|靜岡", "hamamatsu": "浜松", "nagano": "長野", "kanazawa": "金沢", "chiba": "千葉", "yokohama": "横浜",
    "saitama": "さいたま|埼玉", "kumamoto": "熊本", "kagoshima": "鹿児島|鹿兒島", "ibusuki": "指宿", "hofu": "防府",
    "hong kong": "香港", "macau": "澳門|澳门", "xiamen": "廈門|厦门", "shanghai": "上海", "beijing": "北京",
    "seoul": "서울|首爾", "busan": "부산", "daegu": "대구", "gyeongju": "경주", "chuncheon": "춘천", "jtbc": "jtbc",
    "gunsan": "군산", "incheon": "인천", "goyang": "고양", "jeonju": "전주",
}


def aims_name_match(local: dict, a: dict) -> bool:
    if same_race(local, a):
        return True
    an = a["name"].lower()
    hay = " ".join(filter(None, [local.get("name"), local.get("name_local"), local.get("city"), local.get("venue")]))
    for en, cjk in CITY_CJK.items():
        if re.search(r"\b" + re.escape(en) + r"\b", an) and re.search(cjk, hay, re.I):
            return True
    return False


def match_aims(races: list[dict], aims_races: list[dict]) -> list[dict]:
    """Mark local races as AIMS certified (same date, same country, matching city); return the rest."""
    leftovers = []
    for a in aims_races:
        named = [r for r in races if r["race_date"] == a["race_date"] and r["country"] == a["country"]
                 and aims_name_match(r, a)]
        if named:
            r = named[0]
            r["aims_certified"] = True
            if r["name"] != a["name"] and not re.search(r"[A-Za-z]{4}", r["name"]):
                r["name_local"], r["name"] = r["name"], re.sub(r"\s+–\s+Elite Race$", "", a["name"])
            r["sources"] = list(dict.fromkeys(r["sources"] + ["AIMS"]))
            r["source_urls"] = list(dict.fromkeys(r["source_urls"] + a["source_urls"]))
        else:
            leftovers.append(a)
    return leftovers


def load_manual() -> list[dict]:
    try:
        rows = json.loads(MANUAL.read_text(encoding="utf-8")).get("races", [])
    except (FileNotFoundError, json.JSONDecodeError) as e:
        log("manual races not loaded:", e)
        return []
    from common import blank_race

    out = []
    for m in rows:
        r = blank_race(**{k: v for k, v in m.items() if not k.startswith("_")})
        r["sources"] = ["My list"]
        r["source_urls"] = [m.get("registration_url")] if m.get("registration_url") else []
        out.append(r)
    return out


# ---------------------------------------------------------------- English names
def _lang(text: str) -> str:
    if re.search(r"[\uac00-\ud7af]", text):
        return "ko"
    if re.search(r"[\u3040-\u30ff]", text):
        return "ja"
    return "zh-TW"


def machine_translate(f: Fetcher, text: str) -> str | None:
    """Free MyMemory API (no key; ~5,000 characters a day). Returns None on any problem."""
    try:
        r = f.s.get(MT_URL, params={"q": text[:450], "langpair": f"{_lang(text)}|en"}, timeout=20)
        j = r.json()
        out = (j.get("responseData") or {}).get("translatedText") or ""
        if j.get("responseStatus") != 200 or not out or "MYMEMORY WARNING" in out.upper() or NON_LATIN.search(out):
            return None
        out = re.sub(r"\s+", " ", out).strip(" -–")
        return out[:1].upper() + out[1:]
    except Exception:  # noqa: BLE001
        return None


def add_english_names(races: list[dict], f: Fetcher) -> dict:
    try:
        manual = json.loads(NAMES.read_text(encoding="utf-8")).get("names", {})
    except (FileNotFoundError, json.JSONDecodeError):
        manual = {}
    try:
        cache = json.loads(TRANS_CACHE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        cache = {}
    stats = {"manual": 0, "cached": 0, "machine": 0, "untranslated": 0}
    budget = MT_PER_RUN
    for r in races:
        name = r.get("name") or ""
        if not NON_LATIN.search(name):
            continue
        if name in manual:
            en, stats["manual"] = manual[name], stats["manual"] + 1
        elif name in cache:
            en, stats["cached"] = cache[name], stats["cached"] + 1
        elif budget > 0:
            budget -= 1
            en = machine_translate(f, name)
            if en:
                cache[name] = en
                stats["machine"] += 1
            time.sleep(1)
        else:
            en = None
        if en:
            r["name_local"] = r.get("name_local") or name
            r["name"] = en
        else:
            stats["untranslated"] += 1
    TRANS_CACHE.parent.mkdir(parents=True, exist_ok=True)
    TRANS_CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=0, sort_keys=True), encoding="utf-8")
    return stats


def finalise(r: dict, fx: dict, previous: dict[str, dict]) -> dict:
    r["id"] = race_id(r.get("name_local") or r["name"], r["race_date"], r["country"])  # original name keeps ids stable
    lo, hi = r.pop("cost_low", None), r.pop("cost_high", None)
    if lo is not None and r.get("cost_currency"):
        r["cost_cad"] = to_cad(lo, r["cost_currency"], fx)
        r["cost_cad_max"] = to_cad(hi, r["cost_currency"], fx) if hi and hi != lo else None
        r["cost_original"] = r.get("cost_original") or fmt_money(r["cost_currency"], lo, hi)
    elif r.get("cost_amount") is not None:  # manual races
        r["cost_cad"] = to_cad(r.pop("cost_amount"), r.get("cost_currency"), fx)
    reasons = []
    if MAJORS.search((r.get("name") or "").strip()) or MAJORS.search((r.get("name_local") or "").strip()):
        reasons.append("World Marathon Major")
    if r.get("aims_certified"):
        reasons.append("AIMS Certified")
    if r.get("entry_type") == "Lottery":
        reasons.append("Lottery Entry")
    if r.get("sold_out"):
        reasons.append("Sold Out")
    if r.pop("hot", False):
        reasons.append("Popular on 運動筆記")
    r["popularity_flag"] = bool(reasons)
    r["popularity_reason"] = ", ".join(reasons) or None
    old = previous.get(r["id"])
    r["first_seen_date"] = old["first_seen_date"] if old else TODAY.isoformat()
    r["last_seen_date"] = TODAY.isoformat()
    for k in ("venue", "detail_url"):
        r.pop(k, None)
    return r


# ---------------------------------------------------------------- main
def main() -> int:
    previous_doc = {}
    if DATA.exists():
        try:
            previous_doc = json.loads(DATA.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            log("existing races.json unreadable – starting fresh")
    previous = {r["id"]: r for r in previous_doc.get("races", [])}
    first_run = not previous

    f = Fetcher(delay=2.0)
    cache = load_cache()
    fx = load_fx(f, previous_doc.get("fx"))
    health, collected = {}, []
    order = sorted((s for s in CONFIG["sources"] if s.get("enabled") and s["id"] in SOURCES), key=lambda s: s["priority"])
    fetchers = []

    def run_one(s: dict):
        fs = Fetcher(delay=2.0)  # one per site: the 2-second gap applies per site, sites run side by side
        fetchers.append(fs)
        t0 = time.time()
        try:
            got = SOURCES[s["id"]](fs, cache)
            for r in got:
                r["_priority"] = s["priority"]
            log(f"{s['name']}: {len(got)} races in {time.time() - t0:.0f}s")
            return s, got, None, round(time.time() - t0)
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            log(f"{s['name']}: FAILED – {e}")
            return s, [], e, round(time.time() - t0)

    with ThreadPoolExecutor(max_workers=len(order) or 1) as pool:
        for s, got, err, secs in pool.map(run_one, order):
            collected += got
            if err is None:
                health[s["name"]] = {"ok": True, "count": len(got), "error": None, "last_success": TODAY.isoformat(), "seconds": secs}
            else:
                prev = (previous_doc.get("source_health") or {}).get(s["name"], {})
                health[s["name"]] = {"ok": False, "count": 0, "error": str(err)[:300], "last_success": prev.get("last_success")}

    # merge duplicates across sources (higher priority first)
    collected.sort(key=lambda r: (r["_priority"], r["race_date"]))
    merged: list[dict] = []
    directory_srcs = {"World's Marathons", "Marathon Index", "Ahotu", "Watched link"}
    for r in collected:
        from_dir = bool(directory_srcs & set(r.get("sources", [])))
        if r.get("date_unconfirmed"):
            near = [m for m in merged if m["country"] == r["country"] and
                    abs((dt.date.fromisoformat(m["race_date"]) - dt.date.fromisoformat(r["race_date"])).days) <= 45 and
                    (same_race(dict(m, race_date=r["race_date"]), r) or aims_name_match(dict(m, race_date=r["race_date"]), r))]
            if near:
                merge_into(near[0], {k: v for k, v in r.items() if k not in ("race_date", "date_unconfirmed", "note")})
                continue
        twin = next((m for m in merged if same_race(m, r) or
                     (from_dir and m["race_date"] == r["race_date"] and m["country"] == r["country"] and aims_name_match(m, r))), None)
        if twin:
            merge_into(twin, r)
        else:
            merged.append(r)

    if src_cfg("aims").get("enabled"):
        try:
            aims_races = aims.parse(f.get(aims.URL, "aims"))
            extra = match_aims(merged, aims_races)
            merged += [a for a in extra if a["race_date"] >= TODAY.isoformat()]
            health["AIMS"] = {"ok": True, "count": len(aims_races), "error": None, "last_success": TODAY.isoformat()}
        except Exception as e:  # noqa: BLE001
            health["AIMS"] = {"ok": False, "count": 0, "error": str(e)[:300], "last_success": None}

    manual = load_manual()
    for m in manual:
        twin = next((r for r in merged if same_race(r, m)), None)
        if twin:
            merge_into(m, twin)
            merged[merged.index(twin)] = m
        else:
            merged.append(m)
    health["My list"] = {"ok": True, "count": len(manual), "error": None, "last_success": TODAY.isoformat()}

    for r in merged:
        r.pop("_priority", None)
    names_stats = add_english_names(merged, f)
    log("English names:", names_stats)
    races = [finalise(r, fx, previous) for r in merged if r.get("race_date")]

    # keep races a failed source listed yesterday; drop the long-unseen and the past
    ok_sources = {k for k, v in health.items() if v["ok"]}
    seen_ids = {r["id"] for r in races}
    unseen_limit = (TODAY - dt.timedelta(days=CONFIG.get("drop_unseen_after_days", 14))).isoformat()
    for old in previous.values():
        if old["id"] in seen_ids or old.get("expected"):
            continue
        if any(s not in ok_sources for s in old.get("sources", [])) or old.get("last_seen_date", "") >= unseen_limit:
            races.append(old)
    past_limit = (TODAY - dt.timedelta(days=CONFIG.get("drop_past_after_days", 7))).isoformat()
    not_races = re.compile(r"練習会|バーチャル|オンライン|virtual|online|취소", re.I)
    races = [r for r in races if r["race_date"] >= past_limit
             and not not_races.search((r.get("name_local") or "") + " " + r["name"])]

    # remember every edition, then add "expected" next editions for races with no new date yet
    hist = history.load()
    history.record(hist, list(previous.values()) + races + PAST_EDITIONS)
    expected = history.project(hist, races, TODAY)
    for r in expected:
        r["id"] = race_id(r.get("name_local") or r["name"], "expected", r["country"])
        old = previous.get(r["id"])
        r["first_seen_date"] = old["first_seen_date"] if old else TODAY.isoformat()
        r["last_seen_date"] = TODAY.isoformat()
    races += expected
    history.save(hist)
    log(f"history: {len(hist)} race series; expected editions added: {len(expected)}")
    races.sort(key=lambda r: (r["race_date"], r["name"]))

    requests_made = f.requests_made + sum(x.requests_made for x in fetchers)
    doc = {"generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "fx": fx,
           "source_health": health, "requests_made": requests_made, "english_names": names_stats, "directories": DIRECTORY_STATS, "races": races}
    DATA.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=0), encoding="utf-8")
    new = [] if first_run else [r for r in races if r["id"] not in previous and not r.get("expected")]
    NEW_TODAY.write_text(json.dumps(new, ensure_ascii=False, indent=1), encoding="utf-8")

    by_region = {}
    for r in races:
        by_region[r["region"]] = by_region.get(r["region"], 0) + 1
    log(f"wrote {len(races)} races {by_region}; with CAD cost: {sum(1 for r in races if r.get('cost_cad'))}; "
        f"new today: {len(new)}; requests: {requests_made}")
    return 0 if any(v["ok"] for v in health.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
