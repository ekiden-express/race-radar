# Global Race Radar

A personal running-race dashboard for **East Asia, Southeast Asia and Canada**. Every morning a GitHub Action reads local race calendars, converts entry fees to Canadian dollars, opens an issue listing any new races that match your alert rules, and updates a filterable web page with direct registration links.

Everything runs on free tiers: a public GitHub repo, GitHub Actions on standard runners, GitHub Pages and a free exchange-rate API.

## Turn on the web page (one time)

1. In this repo go to **Settings → Pages**.
2. Under **Build and deployment**, set **Source** to **Deploy from a branch**, pick **main** and **/ (root)**, and click **Save**.
3. After a minute or two the page is live at `https://<your-username>.github.io/race-radar/`.

## Get alerts by email

Alerts arrive as GitHub issues labelled `race-alert`. To get them by email, click **Watch → Custom → Issues** at the top of the repo. (GitHub emails you about issues in repos you watch.)

## What it reads

| Source | Covers | What it gives | Notes |
|---|---|---|---|
| [運動筆記](https://running.biji.co/index.php?q=competition) | Taiwan, plus big races in Japan, Hong Kong, Korea and China | Date, distances, registration window, venue; **fees** from each race page | The best source. Fees are read for races you can still enter. |
| [RUNNET](https://runnet.jp) | Japan | Date, distances, entry period | Only the most-viewed full and half marathons with entries open (2 pages each), to keep the list manageable. |
| [마라톤온라인](http://www.roadrun.co.kr/schedule/list.php) | South Korea | Date, distances, venue, organiser's site | Races with a 10 km or longer. |
| [JomRun](https://www.jomrun.com/events) | Malaysia, Singapore, Thailand, Indonesia, Philippines, Brunei, Cambodia, Myanmar, Hong Kong, Japan | Date, venue, distances, registration close date | JomRun shows fees only after you log in, so its races never get a CAD price. |
| [AIMS calendar](https://aims-worldrunning.org/calendar.html) | AIMS-certified races in all three regions | Certification, English race names | Used to mark races as AIMS certified and to add certified races no local site lists. |
| [World's Marathons](https://worldsmarathons.com) | ~370 races in our regions (found by place names in its race addresses) | Latest edition's date, city, country | Fills gaps such as Laos, Cambodia, Vietnam and Canada. Past editions feed "Expected" entries. |
| [Marathon Index](https://marathon-index.com) | Well-known races worldwide | Next date (sometimes an estimate) | Shown with a **DATE TBC** badge unless a local source confirms the date. |
| `config/watch_urls.json` | Any race page you paste in | Latest edition's date | For races the other sources miss. Works with World's Marathons, Marathon Index and Ahotu pages. |
| `config/manual_races.json` | Anything you add | Whatever you type in | **This is how Canada is covered for now** – see below. |

### Canada

RunGuides' `robots.txt` asks automated tools not to read its `/runs` listing pages, so the scraper doesn't use it. Race Roster's search is built in JavaScript and has no readable listing. Until a scraper-friendly Canadian calendar turns up, Canada comes from AIMS (a few certified races) plus **`config/manual_races.json`**, which starts with a handful of major BC and Ontario races. Add your own by copying a block in that file on GitHub and committing; the next run picks it up.

## Expected races (date TBC)

Every race the scraper sees is remembered in `data/history.json`. When a race has passed and no new date has been announced, the dashboard shows next year's edition as **Expected**, on the same weekday 52 weeks later, with a note saying when it was last held. As soon as a source lists the real date, the expected entry is replaced. Races not held for about two years are dropped. Untick **Include expected races** to hide them.

## Changing what it does

- **Alerts:** edit `config/alerts.json` (regions, countries, distances, open registration only, high demand only, trail races).
- **Sources:** edit `config/sources.json` to turn a source off, change merge priority, or limit how many race pages it opens per run.
- **Your races:** edit `config/manual_races.json`.
- **Track a race the sources miss:** paste its World's Marathons, Marathon Index or Ahotu link into `config/watch_urls.json`.
- **Fix an English name:** edit `config/name_translations.json`.
- **Run it now:** **Actions → Daily race update → Run workflow**. It also runs whenever you change a file in `config/` or `scripts/`.

## How it works

- Runs daily at 14:00 UTC (6 AM PST / 7 AM PDT). GitHub sometimes starts scheduled jobs a little late.
- Each source has its own parser in `scripts/sources/`. If one site fails, the others still run, and races that site listed yesterday are kept until it comes back. The page shows which sources failed.
- Fees are converted with [ExchangeRate-API](https://www.exchangerate-api.com)'s open endpoint (rates are units per 1 CAD, so CAD = amount ÷ rate). If the API is down, yesterday's rates are reused and flagged.
- Race pages opened for fees are cached for 7 days in `data/cache/details.json`, so the job stays polite and fast.
- The same race listed by two sources is merged (same date and country, similar name). AIMS matches also need a matching city.
- Races are dropped 7 days after race day, or after 14 days without any source listing them.
- The scraper identifies itself, waits 2 seconds between requests to the same site and respects `robots.txt`.

## Saved races and calendars

Saving a race (☆ Save) and setting **Interested / Registered / Done** is stored in your browser. Use **Export saved** and **Import** to move your list between your phone and laptop. Each race has a **📅 .ics** download (race day plus registration open/close dates) and a Google Calendar link; **Saved races (.ics)** downloads all of them at once.

## Run it on your own computer

```bash
pip install -r requirements.txt
python scripts/fetch_races.py
python -m http.server     # then open http://localhost:8000
```

## Good to know

- GitHub can pause scheduled workflows in public repos after 60 days with no repository activity. The daily data commits normally count as activity; if it ever pauses, re-enable it under **Actions → Daily race update**.
- Always confirm dates and fees on the official race site before booking flights.
