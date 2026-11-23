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
    "biji_list": "https://running.biji.co/index.php?q=competition",
    "biji_detail": "https://running.biji.co/index.php?q=competition&act=info&cid=13162",
    "biji_robots": "https://running.biji.co/robots.txt",
    "jomrun_events": "https://www.jomrun.com/events",
    "jomrun_upcoming": "https://www.jomrun.com/events/recent",
    "jomrun_detail": "https://www.jomrun.com/event/Georgetown-Half-Marathon-2027-Powered-by-JomRun",
    "jomrun_robots": "https://www.jomrun.com/robots.txt",
    "runguides_van": "https://www.runguides.com/vancouver/runs",
    "runguides_detail": "https://www.runguides.com/event/26216/odlum-brown-moustache-miler",
    "runguides_calgary": "https://www.runguides.com/calgary/runs",
    "runguides_montreal": "https://www.runguides.com/montreal/runs",
    "runguides_robots": "https://www.runguides.com/robots.txt",
    "runnet_home": "https://runnet.jp/",
    "runnet_robots": "https://runnet.jp/robots.txt",
    "roadrun_list": "http://www.roadrun.co.kr/schedule/list.php",
    "aims": "https://aims-worldrunning.org/calendar.html",
    "fx": "https://open.er-api.com/v6/latest/CAD",
}
report = {}
for name, url in URLS.items():
    try:
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
(OUT / "report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
print(json.dumps(report, indent=1))
