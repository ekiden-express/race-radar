"""One-off: save raw copies of candidate source pages."""
import json, pathlib, time, gzip
import requests
OUT = pathlib.Path("data/probe"); OUT.mkdir(parents=True, exist_ok=True)
H = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36 GlobalRaceRadar/1.0",
     "Accept-Language": "en-CA,en;q=0.9"}
URLS = {
    "wm_sitemap_index": "https://www.worldsmarathons.com/index-sitemap-en.xml",
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
import re as _re
idx = (OUT / "wm_sitemap_index.html").read_text(encoding="utf-8", errors="replace")
for i, u in enumerate(_re.findall(r"<loc>([^<]+)</loc>", idx)[:12]):
    try:
        r = requests.get(u, headers=H, timeout=30); c = r.content
        if c[:2] == b"\x1f\x8b": c = gzip.decompress(c)
        (OUT / f"wm_sm_{i}.xml").write_bytes(c); report[f"wm_sm_{i}"] = {"url": u, "status": r.status_code, "bytes": len(c)}
    except Exception as e:
        report[f"wm_sm_{i}"] = {"url": u, "error": str(e)}
    time.sleep(2)
(OUT / "report3.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
print(json.dumps(report, indent=1))
