# 🐸 Universal SEO Crawler: Open-Source Screaming Frog Alternative

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![Architecture: SQLite WAL](https://img.shields.io/badge/Architecture-SQLite%20WAL-green.svg)]()
[![Output: Single Master CSV](https://img.shields.io/badge/Output-Single%20Master%20CSV-purple.svg)]()

> Most desktop crawlers either lock you behind a 500-page limit or eat 6 GB of RAM and crash when a site exceeds 20,000 pages. Universal SEO Crawler is a free Python alternative built to crawl 100,000+ URLs on a standard laptop without memory leaks, exporting every page, image, and asset into a single clean CSV spreadsheet.

---

## ⚡ Why We Built This: Screaming Frog Comparison

| Feature | Screaming Frog SEO Spider | Universal SEO Crawler |
| :--- | :---: | :---: |
| **Price** | ~$259 / year per seat | **100% Free & Open Source (MIT)** |
| **Free Crawl Limit** | Capped at 500 URLs | **Unlimited (Built for 100,000+ URLs)** |
| **Memory Usage** | Consumes gigabytes of RAM at scale | **Flat ~120 MB RAM (Disk-backed SQLite WAL)** |
| **Output File** | Multiple fragmented spreadsheets | **1 Single Consolidated Master CSV** |
| **Asset Discovery** | HTML, Images, JS, CSS, PDFs | **HTML, Images, JS, CSS, PDFs, Fonts** |
| **Image Inlink Alt Tracking**| Yes | **Yes (Tracks parent URL and alt per instance)** |
| **Duplicate Canonical Check**| Yes | **Yes (Catches multiple conflicting canonical tags)** |
| **Mixed Content Warning** | Yes | **Yes (Flags HTTP assets on HTTPS pages)** |
| **CLI & Headless Use** | Requires paid license and GUI setup | **Native Async CLI, agent-ready** |
| **Emergency Interrupt** | Risk of losing crawl data on crash | **Safe Ctrl+C flush (Never lose progress)** |

---

## 🚀 Quick Start

### 1. Installation
Clone the repository and install dependencies:
```bash
git clone https://github.com/grvmon/universal-seo-crawler.git
cd universal-seo-crawler

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Run a Crawl
```bash
# Basic run (defaults to 100,000 pages max, 20 concurrent workers)
python crawler.py https://example.com

# Large 100k+ audit with 30 workers saving to a custom file
python crawler.py https://example.com --max-pages 100000 --concurrency 30 --output ./client_audit.csv
```

---

## 🏗️ How It Handles 100k+ URLs Without Crashing

Standard desktop crawlers keep every discovered URL, link relation, and image instance in system memory. On a 100,000-page site with millions of internal links, Python or Java easily chews through 4 to 6 GB of RAM, slowing down to a crawl before eventually crashing.

**Universal SEO Crawler uses an embedded SQLite WAL architecture:**
1. **Constant memory on disk:** Fast in-memory queues feed workers, but every discovered URL and link reference is batched directly to a local SQLite database in WAL mode. Memory stays steady at roughly 120 MB whether you are auditing 500 pages or 500,000.
2. **Streaming CSV exporter:** Instead of building a massive list in memory before saving, records stream from SQLite into your CSV in 5,000-row chunks.
3. **Never lose progress on cancel:** Pressing `Ctrl+C` safely commits all pending buffers and exports your CSV with whatever was collected up to that exact second.

---

## 📊 The 33-Column Master CSV Schema

Every discovered resource (HTML pages, images, scripts, stylesheets, PDFs, and fonts) lands in a single spreadsheet:

```
 1. URL                          12. Indexability Reason          23. First H1 Text
 2. Resource Type                13. Robots.txt Status            24. H2 Count
 3. Status Code                  14. Canonical URL                25. Word Count
 4. Status Message               15. Canonical Status             26. Image Alt Text
 5. Redirect Target              16. Meta Robots                  27. Image Alt Status
 6. Size (KB)                    17. X-Robots-Tag                 28. Image Size Warning
 7. TTFB (ms)                    18. Title                        29. Has Schema JSON-LD
 8. Crawl Depth                  19. Title Length                 30. Schema Types
 9. Inlinks Count                20. Meta Description             31. OG Title
10. Discovered On (Parent URL)   21. Meta Description Length      32. OG Image
11. Indexability                 22. H1 Count                     33. Issues & Warnings
```

---

## ⚙️ CLI Reference

```
usage: crawler.py [-h] [--max-pages MAX_PAGES] [--max-depth MAX_DEPTH]
                  [--concurrency CONCURRENCY] [--timeout TIMEOUT]
                  [--output OUTPUT] [--delay DELAY] [--no-external-assets]
                  [--keep-db]
                  url

Universal All-Resource Website Crawler & SEO Audit Engine (100k+ Scale)

positional arguments:
  url                   Target seed URL (e.g., https://example.com)

optional arguments:
  -h, --help            show this help message and exit
  --max-pages, -m       Maximum total resources to crawl (default: 100000)
  --max-depth, -d       Maximum crawl depth from seed (default: 12)
  --concurrency, -c     Number of concurrent async workers (default: 20)
  --timeout, -t         HTTP request timeout in seconds (default: 12.0)
  --output, -o          Destination path for single master CSV (default: ./master_audit_report.csv)
  --delay               Politeness delay in seconds between requests (default: 0.0)
  --no-external-assets  Do not check external CDN images or scripts (default: False)
  --keep-db             Keep the SQLite database cache on disk after export (default: False)
```

---

## 🤝 Contributing & License
Contributions, bug reports, and pull requests are welcome.  
Licensed under the [MIT License](LICENSE).
