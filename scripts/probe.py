"""One-off: save raw copies of each source page so parsers can be written against real HTML."""
import json
import pathlib
import time

import requests

OUT = pathlib.Path("data/probe")
OUT.mkdir(parents=True, exist_ok=True)
H = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36 GlobalRaceRadar/1.0",
    "Accept-Language": "en-CA,en;q=0.9,zh-TW;q=0.8,ja;q=0.7,ko;q=0.6",
}
URLS = {
    "trackie_robots": "https://www.trackie.com/robots.txt",
    "trackie_events": "https://www.trackie.com/events/",
    "raceroster_robots": "https://raceroster.com/robots.txt",
    "raceroster_search": "https://raceroster.com/search?q=&t=running&l=Vancouver%2C+BC",
    "runningroom_robots": "https://www.runningroom.com/robots.txt",
    "runningroom_events": "https://www.runningroom.com/hm/inside.php?id=2786",
    "canadarunningseries": "https://canadarunningseries.com/",
    "bcathletics_robots": "https://www.bcathletics.org/robots.txt",
    "bcathletics_road": "https://www.bcathletics.org/road-running/calendar",
}
report = {}
for name, url in URLS.items():
    try:
        if url.startswith("POST|"):
            _, u, body = url.split("|")
            r = requests.post(u, data=dict(x.split("=") for x in body.split("&")), headers=H, timeout=30)
        elif url.endswith(".gz"):
            import gzip
            r = requests.get(url, headers=H, timeout=30)
            r._content = gzip.decompress(r.content) if r.content[:2] == b"\x1f\x8b" else r.content
        else:
            r = requests.get(url, headers=H, timeout=30)
        if not r.encoding or r.encoding.lower() == "iso-8859-1":
            r.encoding = r.apparent_encoding
        ext = "json" if name == "fx" else ("txt" if "robots" in name else "html")
        (OUT / f"{name}.{ext}").write_text(r.text, encoding="utf-8")
        report[name] = {"url": url, "status": r.status_code, "bytes": len(r.content), "final_url": r.url,
                        "server": r.headers.get("server"), "encoding": r.encoding}
    except Exception as e:  # noqa: BLE001
        report[name] = {"url": url, "error": str(e)}
    time.sleep(2)
(OUT / "report3.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
print(json.dumps(report, indent=1))
