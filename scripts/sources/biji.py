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
PARSER_VERSION = 4
EXCLUDE = re.compile(r"LAVA|鐵人|三鐵|二鐵|游泳|自行車|單車|健走(?!.*跑)", re.I)
SEA = {"Singapore", "Malaysia", "Thailand", "Vietnam", "Philippines", "Indonesia"}
EAST_ASIA = {"Taiwan", "Japan", "Hong Kong", "Macau", "South Korea", "China"}


TW_EN = {
    "臺北市": "Taipei", "新北市": "New Taipei", "桃園市": "Taoyuan", "臺中市": "Taichung", "臺南市": "Tainan",
    "高雄市": "Kaohsiung", "基隆市": "Keelung", "新竹市": "Hsinchu City", "嘉義市": "Chiayi City",
    "新竹縣": "Hsinchu County", "苗栗縣": "Miaoli", "彰化縣": "Changhua", "南投縣": "Nantou", "雲林縣": "Yunlin",
    "嘉義縣": "Chiayi County", "屏東縣": "Pingtung", "宜蘭縣": "Yilan", "花蓮縣": "Hualien", "臺東縣": "Taitung",
    "澎湖縣": "Penghu", "金門縣": "Kinmen", "連江縣": "Matsu",
}


def _place(label: str) -> tuple[str | None, str | None]:
    if label in OVERSEAS:
        return OVERSEAS[label]
    if TAIWAN_SUFFIX.search(label):
        label = label.replace("台", "臺")
        return "Taiwan", TW_EN.get(label, label)
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
    # bump PARSER_VERSION when this changes so cached pages are read again
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
    # fees: look in every window that starts at a fee keyword, stop before prize money or insurance
    cur = "TWD" if race["country"] == "Taiwan" else race.get("cost_currency")
    found: list[float] = []
    for m in re.finditer(r"報\s*名\s*費|參\s*加\s*費|參\s*賽\s*費|參\s*與\s*費|費\s*用|價格|收費|早鳥", text):
        win = text[m.start(): m.start() + 700]
        win = re.split(r"獎金|獎勵|名次|頒獎|保險|贊助|捐款|海外|美元|USD", win)[0]
        # leave out concession prices (students, children, seniors, para-athletes)
        win = re.sub(r"(學生|高中|國中|小學|兒童|親子|長者|身障|殘障|視障)[^|；;。\n]{0,25}", " ", win)
        c2, amts = parse_fees(win, cur or "TWD")
        cur = cur or c2
        found += [v for v in amts if cur and plausible(cur, v)]
    if cur == "JPY":
        # Japanese races list many surcharges and packages; keep the standard runner price only
        std = [float(x.replace(",", "")) for x in re.findall(r"(?:普通|一般|國內)[^0-9]{0,12}([\d,]{4,})\s?(?:日圓|日元|円|圓)", text)]
        found = [v for v in std if plausible("JPY", v)]
    if found and cur:
        lo, hi = min(found), max(found)
        upd.update(cost_currency=cur, cost_low=lo, cost_high=hi, cost_original=fmt_money(cur, lo, hi))
    else:
        i = text.find("費")
        upd["fee_hint"] = text[max(0, i - 40): i + 260].replace("\n", " | ") if i >= 0 else None
    if re.search(r"\bAIMS\b", text):
        upd["aims_certified"] = True
    if re.search(r"抽籤|抽選", text):
        upd["entry_type"] = "Lottery"
    return upd
