"""RUNNET (runnet.jp) – Japan. Only the most-viewed races with entries open, so the list stays manageable."""
from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from common import blank_race, norm_distances

BASE = "https://runnet.jp"
SEARCH = BASE + "/entry/runtes/user/pc/RaceSearchZZSDetailAction.do?command=search&available=1&distanceClass={cls}"
PAGE = BASE + "/entry/runtes/user/pc/RaceSearchZZSDetailAction.do?command=page&&specialize=null&pageIndex={n}"
DISTANCE_CLASSES = {"1": "Marathon", "2": "Half Marathon"}  # RUNNET's own classes

PREF_EN = {
    "北海道": "Hokkaido", "青森県": "Aomori", "岩手県": "Iwate", "宮城県": "Miyagi", "秋田県": "Akita", "山形県": "Yamagata",
    "福島県": "Fukushima", "茨城県": "Ibaraki", "栃木県": "Tochigi", "群馬県": "Gunma", "埼玉県": "Saitama", "千葉県": "Chiba",
    "東京都": "Tokyo", "神奈川県": "Kanagawa", "新潟県": "Niigata", "富山県": "Toyama", "石川県": "Ishikawa", "福井県": "Fukui",
    "山梨県": "Yamanashi", "長野県": "Nagano", "岐阜県": "Gifu", "静岡県": "Shizuoka", "愛知県": "Aichi", "三重県": "Mie",
    "滋賀県": "Shiga", "京都府": "Kyoto", "大阪府": "Osaka", "兵庫県": "Hyogo", "奈良県": "Nara", "和歌山県": "Wakayama",
    "鳥取県": "Tottori", "島根県": "Shimane", "岡山県": "Okayama", "広島県": "Hiroshima", "山口県": "Yamaguchi",
    "徳島県": "Tokushima", "香川県": "Kagawa", "愛媛県": "Ehime", "高知県": "Kochi", "福岡県": "Fukuoka", "佐賀県": "Saga",
    "長崎県": "Nagasaki", "熊本県": "Kumamoto", "大分県": "Oita", "宮崎県": "Miyazaki", "鹿児島県": "Kagoshima", "沖縄県": "Okinawa",
}


def _jdate(el) -> str | None:
    if el is None:
        return None
    t = el.get_text("", strip=True)
    m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", t)
    return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else None


def parse_results(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    out = []
    for item in soup.select("#listGroup li.item"):
        a = item.select_one(".item-title > a") or item.select_one(".item-title a")
        if not a:
            continue
        name = a.get_text(strip=True)
        if re.search(r"練習会|バーチャル|オンライン|virtual|online", name, re.I):
            continue  # practice sessions and virtual runs, not races
        url = urljoin(BASE, a.get("href", ""))
        race_date = _jdate(item.select_one("p.date"))
        if not race_date:
            continue
        pel = item.select_one("p.place")
        place = pel.get_text(strip=True) if pel else ""
        pm = re.match(r"(.+?[都道府県])(?:（(.+?)）)?", place)
        pref, town = (pm.group(1), pm.group(2)) if pm else (place, None)
        dists, reg_open, reg_close = "", None, None
        for tr in item.select("table.infoTable tr"):
            th = tr.find("th").get_text(strip=True) if tr.find("th") else ""
            td = tr.find("td")
            if not td:
                continue
            if th.startswith("種目"):
                dists = re.sub(r"\s+", "", td.get_text(" ", strip=True)).replace(",", ", ")
            elif th.startswith("エントリー期間"):
                ds = re.findall(r"(\d{4})年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", td.get_text(" ", strip=True))
                if ds:
                    reg_open = "%04d-%02d-%02d" % tuple(map(int, ds[0]))
                    reg_close = "%04d-%02d-%02d" % tuple(map(int, ds[-1])) if len(ds) > 1 else None
        en_pref = PREF_EN.get(pref, pref)
        out.append(blank_race(
            name=name, region="East Asia", country="Japan",
            city=(f"{town}, {en_pref}" if town else en_pref) or None, race_date=race_date,
            distances=norm_distances(dists.replace("フル", "marathon ").replace("ハーフ", "half marathon ")),
            distances_raw=dists or None, surface="Trail" if "トレイル" in name else "Road",
            reg_open_date=reg_open, reg_close_date=reg_close, cost_currency="JPY",
            entry_type="Lottery" if re.search(r"抽選", item.get_text()) else None,
            registration_url=url, detail_url=url, source_urls=[url], sources=["RUNNET"],
        ))
    return out
