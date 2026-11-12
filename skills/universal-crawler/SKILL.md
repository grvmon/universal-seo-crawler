---
name: universal-crawler
description: Free, open-source technical SEO crawler built for 100k+ URLs. Crawls all assets on a flat ~120 MB RAM footprint and exports to a single 33-column CSV.
---

# Universal SEO Crawler Skill

Use this skill when you need to audit, diagnose, or crawl a website at scale (up to 100,000+ URLs) to uncover technical and on-page SEO issues, broken links, missing meta tags, mixed content, or asset bottlenecks.

## Core Capabilities
- **Universal Asset Discovery:** Crawls HTML pages, images, JavaScript files, CSS stylesheets, documents (PDFs), and web fonts.
- **Inlink and Context Tracking:** Tracks every referring page, anchor text, and image `alt` text attribute per occurrence.
- **Single Master CSV Output:** Exports a 33-column unified spreadsheet ready for Excel, Google Sheets, or Python data analysis.
- **100k+ Scale Ready:** Uses SQLite WAL mode to keep memory constant at ~120 MB RAM.

## How to Run a Crawl

### 1. Basic Audit
```bash
python /Users/gauravmongia/universal_crawler/crawler.py https://example.com --max-pages 500 --output ./audit.csv
```

### 2. Deep 100k+ Enterprise Crawl
```bash
python /Users/gauravmongia/universal_crawler/crawler.py https://example.com --max-pages 100000 --concurrency 25 --output ./master_audit.csv
```

### 3. Key CLI Options
- `--max-pages`, `-m`: Maximum total resources to crawl (default: `100000`).
- `--max-depth`, `-d`: Click depth cap from homepage (default: `12`).
- `--concurrency`, `-c`: Number of parallel async workers (default: `20`).
- `--output`, `-o`: File destination for the master CSV (default: `./master_audit_report.csv`).
- `--delay`: Politeness delay in seconds between requests (default: `0.0`).
- `--no-external-assets`: Skip checking external CDN assets.
