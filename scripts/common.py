"""Shared helpers: polite HTTP, date parsing, distance and money normalisation."""
from __future__ import annotations

import datetime as dt
import hashlib
import os
import re
import time
import urllib.robotparser
from pathlib import Path
from urllib.parse import urlparse

import requests

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_DIR = ROOT / "data" / "snapshots"
USER_AGENT = (
    "GlobalRaceRadar/1.0 (personal race calendar; +https://github.com/ekiden-express/race-radar) "
    "python-requests"
)
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0 Safari/537.36 GlobalRaceRadar/1.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-CA,en;q=0.9,zh-TW;q=0.8,ja;q=0.7,ko;q=0.6",
}

TODAY = dt.date.today()


class Fetcher:
    """requests.Session with per-host delay, retries, robots.txt and optional snapshots."""

    def __init__(self, delay: float = 2.0, save_snapshots: bool = False):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": USER_AGENT, "Accept-Language": BROWSER_HEADERS["Accept-Language"]})
        self.delay = delay
        self.last: dict[str, float] = {}
        self.robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self.save_snapshots = save_snapshots or os.environ.get("SAVE_SNAPSHOTS") == "1"
        self.requests_made = 0

    def _allowed(self, url: str) -> bool:
        p = urlparse(url)
        base = f"{p.scheme}://{p.netloc}"
        if base not in self.robots:
            rp = urllib.robotparser.RobotFileParser()
            try:
                r = self.s.get(base + "/robots.txt", timeout=15)
                if r.status_code == 200:
                    rp.parse(r.text.splitlines())
                    self.robots[base] = rp
                else:
                    self.robots[base] = None  # no robots.txt: allowed
            except requests.RequestException:
                self.robots[base] = None
        rp = self.robots[base]
        return True if rp is None else rp.can_fetch(USER_AGENT, url)

    def get(self, url: str, snapshot_name: str | None = None, retries: int = 2) -> str:
        if not self._allowed(url):
            raise PermissionError(f"robots.txt disallows {url}")
        host = urlparse(url).netloc
        wait = self.delay - (time.time() - self.last.get(host, 0))
        if wait > 0:
            time.sleep(wait)
        err: Exception | None = None
        for attempt in range(retries):
            headers = None if attempt == 0 else BROWSER_HEADERS  # fallback headers on retry
            try:
                r = self.s.get(url, timeout=20, headers=headers)
                self.last[host] = time.time()
                self.requests_made += 1
                if r.status_code in (429, 500, 502, 503, 504):
                    raise requests.HTTPError(f"HTTP {r.status_code}")
                r.raise_for_status()
                if not r.encoding or r.encoding.lower() == "iso-8859-1":
                    r.encoding = r.apparent_encoding
                text = r.text
                if self.save_snapshots and snapshot_name:
                    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
                    (SNAPSHOT_DIR / f"{snapshot_name}.html").write_text(text, encoding="utf-8")
                return text
            except requests.RequestException as e:
                err = e
                time.sleep(2 * (attempt + 1))
        raise RuntimeError(f"GET {url} failed: {err}")

    def get_json(self, url: str) -> dict:
        r = self.s.get(url, timeout=30)
        r.raise_for_status()
        return r.json()


# ---------------- dates ----------------

def infer_year(month: int, day: int, ref: dt.date | None = None, not_after: dt.date | None = None) -> dt.date:
    """Next occurrence of month/day (allowing ~2 months back), capped at not_after."""
    ref = ref or TODAY
    try:
        d = dt.date(ref.year, month, day)
    except ValueError:
        d = dt.date(ref.year, month, 28)
    if d < ref - dt.timedelta(days=60):
        d = d.replace(year=ref.year + 1)
    if not_after and d > not_after:
        d = d.replace(year=d.year - 1)
    return d


def parse_date_any(text: str, ref: dt.date | None = None) -> dt.date | None:
    """Gregorian, ROC (民國/115年) and month-day formats."""
    if not text:
        return None
    t = text.strip()
    m = re.search(r"(20\d\d)\s*[./\-年]\s*(\d{1,2})\s*[./\-月]\s*(\d{1,2})", t)
    if m:
        return _safe(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.search(r"(?<!\d)(1[01]\d)\s*[./\-年]\s*(\d{1,2})\s*[./\-月]\s*(\d{1,2})", t)  # ROC year
    if m:
        return _safe(int(m.group(1)) + 1911, int(m.group(2)), int(m.group(3)))
    m = re.search(r"(\d{1,2})\s*[月/\-]\s*(\d{1,2})", t)
    if m:
        return infer_year(int(m.group(1)), int(m.group(2)), ref)
    return None


def parse_en_date(text: str) -> dt.date | None:
    from dateutil import parser as dparser

    try:
        return dparser.parse(text, fuzzy=True, default=dt.datetime(TODAY.year, 1, 1)).date()
    except (ValueError, OverflowError):
        return None


def _safe(y: int, m: int, d: int) -> dt.date | None:
    try:
        return dt.date(y, m, d)
    except ValueError:
        return None


# ---------------- distances ----------------

ORDER = ["5K", "10K", "Half Marathon", "Marathon", "Ultra", "Other"]


def km_to_label(km: float) -> str:
    if 4.5 <= km <= 5.5:
        return "5K"
    if 9.5 <= km <= 11:
        return "10K"
    if 20.5 <= km <= 22.5:
        return "Half Marathon"
    if 41.9 <= km <= 43.2:
        return "Marathon"
    if km > 43.2:
        return "Ultra"
    return "Other"


def norm_distances(raw: str) -> list[str]:
    if not raw:
        return []
    t = raw.lower()
    out: set[str] = set()
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*(k(?:m)?|公里|キロ|mi(?:le)?s?)\b", t):
        km = float(m.group(1)) * (1.609 if m.group(2).startswith("mi") else 1)
        out.add(km_to_label(km))
    words = [
        (r"half[\s-]?marathon|半程|半馬|ハーフ|하프|\bhm\b|\b21\.1\b", "Half Marathon"),
        (r"(?<!half )(?<!half-)marathon|全程|全馬|フルマラソン|풀코스|\bfm\b", "Marathon"),
        (r"ultra|超馬|超級馬拉松|ウルトラ|울트라", "Ultra"),
        (r"\b10\s?k\b", "10K"),
        (r"\b5\s?k\b", "5K"),
    ]
    for pat, lab in words:
        if re.search(pat, t):
            out.add(lab)
    return [d for d in ORDER if d in out]


# ---------------- money ----------------

CURRENCY_HINTS = [
    (r"日圓|日元|円|JPY", "JPY"),
    (r"韓元|원|KRW", "KRW"),
    (r"港幣|港元|HK\$", "HKD"),
    (r"NT\$|NTD|新台幣|新臺幣|元", "TWD"),
    (r"HK\$|港幣", "HKD"),
    (r"RM|MYR", "MYR"),
    (r"S\$|SGD", "SGD"),
    (r"¥|円|JPY", "JPY"),
    (r"₩|원|KRW", "KRW"),
    (r"฿|THB|baht", "THB"),
    (r"C\$|CAD", "CAD"),
]


def parse_fees(text: str, default_currency: str | None = None) -> tuple[str | None, list[float]]:
    """Find a currency and all plausible fee amounts in a block of text."""
    cur = None
    for pat, code in CURRENCY_HINTS:
        if re.search(pat, text, re.I):
            cur = code
            break
    cur = cur or default_currency
    amounts = []
    for m in re.finditer(r"(?:NT\$|NTD|HK\$|S\$|C\$|RM|¥|₩|฿|\$)\s?([\d,]+(?:\.\d\d)?)|([\d,]{3,}(?:\.\d\d)?)\s?(?:日圓|日元|圓|元|円|원|NTD)", text):
        v = float((m.group(1) or m.group(2)).replace(",", ""))
        if v > 0:
            amounts.append(v)
    return cur, amounts


def plausible(cur: str, v: float) -> bool:
    lo, hi = {"TWD": (200, 10000), "HKD": (50, 3000), "MYR": (20, 1000), "SGD": (10, 500),
              "JPY": (1000, 60000), "KRW": (10000, 400000), "THB": (200, 10000), "CAD": (10, 500)}.get(cur, (1, 10**7))
    return lo <= v <= hi


def fmt_money(cur: str, lo: float, hi: float | None = None) -> str:
    sym = {"TWD": "NT$", "HKD": "HK$", "MYR": "RM", "SGD": "S$", "JPY": "¥", "KRW": "₩", "THB": "฿", "CAD": "C$"}.get(cur, cur + " ")
    f = lambda v: f"{v:,.0f}" if v == int(v) else f"{v:,.2f}"
    return f"{sym}{f(lo)}" + (f"–{f(hi)}" if hi and hi != lo else "")


def race_id(name: str, date: str, country: str) -> str:
    key = re.sub(r"[\s\W_]+", "", (name or "").lower())
    key = re.sub(r"^20\d\d|20\d\d$", "", key)
    return hashlib.sha1(f"{key}|{date}|{country}".encode()).hexdigest()[:12]


def blank_race(**kw) -> dict:
    r = dict(
        name=None, name_local=None, region=None, country=None, city=None, race_date=None, date_tbd=False,
        distances=[], distances_raw=None, surface="Road",
        cost_original=None, cost_currency=None, cost_cad=None, cost_cad_max=None,
        reg_open_date=None, reg_close_date=None, reg_state_raw=None, reg_closed=False,
        entry_type=None, sold_out=False, aims_certified=False,
        registration_url=None, detail_url=None, source_urls=[], sources=[], note=None,
    )
    r.update(kw)
    return r
