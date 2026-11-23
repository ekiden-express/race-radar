"""마라톤온라인 (roadrun.co.kr) – South Korea's main race calendar. Kept to races with a full, half or 10 km."""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

from common import TODAY, blank_race, infer_year, norm_distances

LIST_URL = "http://www.roadrun.co.kr/schedule/list.php"
VIEW_URL = "http://www.roadrun.co.kr/schedule/view.php?no={no}"


def kor_distances(raw: str) -> list[str]:
    t = raw.replace("풀", "marathon").replace("하프", "half marathon")
    return norm_distances(t)


def parse_list(html: str, year: int | None = None) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    out = []
    for a in soup.find_all("a", href=re.compile(r"open_window\('win', 'view\.php\?no=\d+")):
        b = a.find_parent("b")
        if not b or a.find("img"):
            continue
        tr = a.find_parent("tr")
        tds = tr.find_all("td", recursive=False) if tr else []
        if len(tds) < 4:
            continue
        no = re.search(r"no=(\d+)", a["href"]).group(1)
        name = a.get_text(strip=True)
        dist_el = b.find("font", color="#990000")
        dists_raw = dist_el.get_text(strip=True) if dist_el else ""
        dists = kor_distances(dists_raw)
        if not any(d in dists for d in ("10K", "Half Marathon", "Marathon", "Ultra")):
            continue
        dm = re.search(r"(\d{1,2})/(\d{1,2})", tds[0].get_text(" ", strip=True))
        if not dm:
            continue
        m, d = int(dm.group(1)), int(dm.group(2))
        dt_ = infer_year(m, d) if year is None else infer_year(m, d, ref=TODAY.replace(year=year, month=1, day=1))
        venue = tds[2].get_text(" ", strip=True)
        home = next((x.get("href") for x in tds[3].find_all("a") if (x.get("href") or "").startswith("http")), None)
        view = VIEW_URL.format(no=no)
        out.append(blank_race(
            name=name, name_local=None, region="East Asia", country="South Korea", city=venue,
            race_date=dt_.isoformat(), distances=dists, distances_raw=dists_raw,
            surface="Trail" if re.search(r"트레일|trail", name, re.I) else "Road", cost_currency="KRW",
            registration_url=home or view, detail_url=view, source_urls=[view], sources=["마라톤온라인"],
        ))
    return out
