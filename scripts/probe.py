"""One-off: save raw copies of candidate source pages."""
import json, pathlib, time, gzip
import requests
OUT = pathlib.Path("data/probe"); OUT.mkdir(parents=True, exist_ok=True)
H = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36 GlobalRaceRadar/1.0",
     "Accept-Language": "en-CA,en;q=0.9"}
URLS = {
    "ahotu_robots": "https://www.ahotu.com/robots.txt",
    "ahotu_laos": "https://www.ahotu.com/calendar/running/laos",
    "ahotu_event": "https://www.ahotu.com/event/luang-prabang-half-marathon",
    "mindex_robots": "https://marathon-index.com/robots.txt",
    "mindex_race": "https://marathon-index.com/races/phnom-penh-half-marathon/",
    "mindex_sitemap": "https://marathon-index.com/sitemap.xml",
    "wm_robots": "https://worldsmarathons.com/robots.txt",
    "wm_race": "https://worldsmarathons.com/marathon/luang-prabang-half-marathon",
    "wm_laos": "https://worldsmarathons.com/s/running/laos",
    "finishers_robots": "https://www.finishers.com/robots.txt",
    "raceraves_robots": "https://raceraves.com/robots.txt",
    "timeoutdoors_robots": "https://www.timeoutdoors.com/robots.txt",
    "aims_ics": "https://aims-worldrunning.org/events.ics",
    "aims_laos": "https://aims-worldrunning.org/countries/151.html",
}
report = {}
for name, url in URLS.items():
    try:
        r = requests.get(url, headers=H, timeout=30)
        c = r.content
        if c[:2] == b"\x1f\x8b": c = gzip.decompress(c)
        ext = "txt" if "robots" in name or name.endswith("ics") else "html"
        (OUT / f"{name}.{ext}").write_bytes(c)
        report[name] = {"url": url, "status": r.status_code, "bytes": len(c), "final_url": r.url}
    except Exception as e:
        report[name] = {"url": url, "error": str(e)}
    time.sleep(2)
(OUT / "report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
print(json.dumps(report, indent=1))
