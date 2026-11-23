"""One-off: save raw copies of candidate source pages."""
import json, pathlib, time, gzip
import requests
OUT = pathlib.Path("data/probe"); OUT.mkdir(parents=True, exist_ok=True)
H = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36 GlobalRaceRadar/1.0",
     "Accept-Language": "en-CA,en;q=0.9"}
URLS = {
    "mindex_sitemap0": "https://marathon-index.com/sitemap-0.xml",
    "mindex_lp": "https://marathon-index.com/races/luang-prabang-half-marathon/",
    "mindex_races": "https://marathon-index.com/races/",
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
(OUT / "report2.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
print(json.dumps(report, indent=1))
