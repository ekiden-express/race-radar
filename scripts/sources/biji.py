"""運動筆記 (running.biji.co) – Taiwan plus the overseas races it lists (Japan, HK, Korea, China…)."""
from __future__ import annotations

import re
from urllib.parse import unquote, urljoin

from bs4 import BeautifulSoup

from common import blank_race, norm_distances, parse_date_any, parse_fees, plausible, fmt_money

BASE = "https://running.biji.co"
LIST_URL = BASE + "/index.php?q=competition"

# 運動筆記 place labels for overseas races -> (country, city in English)
OVERSEAS = {
    "日本": ("Japan", None), "東京": ("Japan", "Tokyo"), "大阪": ("Japan", "Osaka"), "京都市": ("Japan", "Kyoto"),
    "名古屋": ("Japan", "Nagoya"), "沖繩": ("Japan", "Okinawa"), "石垣島": ("Japan", "Ishigaki"),
    "香川縣": ("Japan", "Kagawa"), "愛媛縣": ("Japan", "Ehime"), "大分縣": ("Japan", "Oita"),
    "靜岡縣": ("Japan", "Shizuoka"), "福井縣": ("Japan", "Fukui"), "鹿兒島市": ("Japan", "Kagoshima"),
    "北海道": ("Japan", "Hokkaido"), "福岡": ("Japan", "Fukuoka"), "神戶": ("Japan", "Kobe"),
    "香港": ("Hong Kong", "Hong Kong"), "澳門": ("Macau", "Macau"),
    "首爾": ("South Korea", "Seoul"), "韓國": ("South Korea", None), "釜山": ("South Korea", "Busan"),
    "廈門": ("China", "Xiamen"), "上海": ("China", "Shanghai"), "北京": ("China", "Beijing"),
    "新加坡": ("Singapore", "Singapore"), "馬來西亞": ("Malaysia", None), "吉隆坡": ("Malaysia", "Kuala Lumpur"),
    "泰國": ("Thailand", None), "曼谷": ("Thailand", "Bangkok"), "越南": ("Vietnam", None),
    "菲律賓": ("Philippines", None), "印尼": ("Indonesia", None), "峇里島": ("Indonesia", "Bali"),
}
TAIWAN_SUFFIX = re.compile(r"(市|縣)$")
EXCLUDE = re.compile(r"LAVA|鐵人|三鐵|二鐵|游泳|自行車|單車|健走(?!.*跑)", re.I)
SEA = {"Singapore", "Malaysia", "Thailand", "Vietnam", "Philippines", "Indonesia"}
EAST_ASIA = {"Taiwan", "Japan", "Hong Kong", "Macau", "South Korea", "China"}


def _place(label: str) -> tuple[str | None, str | None]:
    if label in OVERSEAS:
        return OVERSEAS[label]
    if TAIWAN_SUFFIX.search(label):
        return "Taiwan", label
    return None, label  # Spain, USA, Dubai…: outside our regions


def parse_list(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    out = []
    for row in soup.select(".competition-list-row"):
        if not row.get("data-month"):
            continue
        a = row.select_one(".competition-name a")
        if not a:
            continue
        name = a.get_text(strip=True)
        if EXCLUDE.search(name):
            continue
        place = row.select_one(".competition-place")
        country, city = _place(place.get_text(strip=True) if place else "")
        if country is None:
            continue
        region = "Southeast Asia" if country in SEA else "East Asia"
        cal = row.select_one("a.competition-date-calendar")
        cal_href = unquote(cal.get("href", "")) if cal else ""
        m = re.search(r"dates=(\d{8})", cal_href)
        if not m:
            continue
        d = m.group(1)
        race_date = f"{d[:4]}-{d[4:6]}-{d[6:]}"
        reg_open = reg_close = None
        rm = re.search(r"報名日期:(\d{4}-\d\d-\d\d)[^~]*~(\d{4}-\d\d-\d\d)", cal_href)
        if rm:
            reg_open, reg_close = rm.group(1), rm.group(2)
        lm = re.search(r"location=([^&]+)", cal_href)
        dists_raw = ", ".join(x.get_text(strip=True) for x in row.select(".event-item"))
        status = row.select_one(".competition-status")
        status_txt = re.sub(r"\s+", "", status.get_text()) if status else ""
        detail = urljoin(BASE, re.sub(r"&subtitle=.*$", "", a.get("href", "")))
        r = blank_race(
            name=name, region=region, country=country, city=city, race_date=race_date,
            distances=norm_distances(dists_raw), distances_raw=dists_raw,
            surface="Trail" if re.search(r"越野|山徑|trail", name, re.I) else "Road",
            reg_open_date=reg_open, reg_close_date=reg_close, reg_state_raw=status_txt or None,
            reg_closed=status_txt == "已截止報名",
            registration_url=detail, detail_url=detail, source_urls=[detail], sources=["運動筆記"],
            venue=lm.group(1).strip() if lm else None,
            hot=bool(row.select_one(".competition-name img.hot-icon")),
        )
        if "延期" in status_txt or "改期" in status_txt:
            r["note"] = "Rescheduled: " + status_txt
        if r["country"] == "Taiwan":
            r["cost_currency"] = "TWD"
        out.append(r)
    return out


def parse_detail(html: str, race: dict) -> dict:
    """Fees, official registration link, AIMS/World Athletics mentions from a race page."""
    soup = BeautifulSoup(html, "lxml")
    upd: dict = {}
    for a in soup.find_all("a"):
        t = a.get_text(strip=True)
        href = a.get("href") or ""
        if t == "線上報名" and href.startswith("http") and "biji.co" not in href:
            upd["registration_url"] = href
        elif t in ("官方網站", "官網", "活動官網") and href.startswith("http") and "registration_url" not in upd:
            upd["official_url"] = href
    for s in soup(["script", "style"]):
        s.decompose()
    text = soup.get_text("\n", strip=True)
    # fee block: from 報名費 to the next deposit/start-time row
    m = re.search(r"報名費(?:用)?(.{0,600}?)(?:押金|保證金|起跑時間|開跑時間|人數限制|集合地點)", text, re.S)
    if m:
        cur, amts = parse_fees(m.group(1), race.get("cost_currency") or "TWD")
        if race["country"] == "Taiwan":
            cur = "TWD"
        amts = [v for v in amts if cur and plausible(cur, v)]
        if amts and cur:
            lo, hi = min(amts), max(amts)
            upd.update(cost_currency=cur, cost_low=lo, cost_high=hi, cost_original=fmt_money(cur, lo, hi))
    if re.search(r"\bAIMS\b", text):
        upd["aims_certified"] = True
    if re.search(r"抽籤|抽選", text):
        upd["entry_type"] = "Lottery"
    return upd
