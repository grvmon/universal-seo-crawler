#!/usr/bin/env python3
"""
Universal All-Resource Website Crawler & SEO Audit Engine (100k+ Enterprise Scale)
===================================================================================
- Crawls all HTML pages, images, JavaScript, CSS stylesheets, PDFs, and fonts.
- Disk-backed SQLite architecture (WAL mode) for rock-solid memory stability at 100,000+ URLs.
- Streams results directly into a single comprehensive master CSV audit report.
"""

import argparse
import asyncio
import csv
import json
import os
import re
import signal
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse, urlunparse, urldefrag
import urllib.robotparser

import httpx
from bs4 import BeautifulSoup
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

console = Console()

# --- Common File Extension Mappings ---
EXT_MAP = {
    # Images
    ".png": "Image", ".jpg": "Image", ".jpeg": "Image", ".webp": "Image",
    ".avif": "Image", ".svg": "Image", ".gif": "Image", ".ico": "Image",
    ".bmp": "Image", ".tiff": "Image",
    # Scripts & Styles
    ".js": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript",
    ".css": "CSS",
    # Documents
    ".pdf": "PDF", ".doc": "Document", ".docx": "Document",
    ".xls": "Document", ".xlsx": "Document", ".zip": "Archive",
    ".tar": "Archive", ".gz": "Archive",
    # Fonts
    ".woff": "Font", ".woff2": "Font", ".ttf": "Font", ".eot": "Font", ".otf": "Font",
    # Media
    ".mp4": "Media", ".webm": "Media", ".mp3": "Media", ".ogg": "Media"
}

def clean_url(url: str) -> str:
    """Normalize and clean URL by removing fragments and query session noise."""
    if not url:
        return ""
    url, _ = urldefrag(url.strip())
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    path = parsed.path or "/"
    return urlunparse((scheme, netloc, path, parsed.params, parsed.query, ""))

def is_valid_http_url(url: str) -> bool:
    """Check if URL has http/https scheme and is not a protocol link."""
    if not url:
        return False
    url_lower = url.strip().lower()
    if url_lower.startswith(("mailto:", "tel:", "javascript:", "data:", "sms:", "#")):
        return False
    parsed = urlparse(url)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)

def guess_resource_type(url: str, content_type: Optional[str] = None) -> str:
    """Classify the resource based on HTTP Content-Type header or URL extension."""
    if content_type:
        ct = content_type.lower()
        if "text/html" in ct or "application/xhtml" in ct:
            return "HTML"
        if ct.startswith("image/"):
            return "Image"
        if "javascript" in ct:
            return "JavaScript"
        if "text/css" in ct:
            return "CSS"
        if "application/pdf" in ct:
            return "PDF"
        if "font/" in ct or "application/font" in ct:
            return "Font"
        if "video/" in ct or "audio/" in ct:
            return "Media"

    path = urlparse(url).path.lower()
    for ext, rtype in EXT_MAP.items():
        if path.endswith(ext):
            return rtype
    return "HTML"

@dataclass
class ResourceRecord:
    url: str
    resource_type: str = "Unknown"
    status_code: Optional[int] = None
    status_message: str = ""
    content_type: str = ""
    size_bytes: int = 0
    ttfb_ms: float = 0.0
    crawl_depth: int = 0
    redirect_target: Optional[str] = None
    is_internal: bool = True
    indexability: str = "Indexable"
    indexability_reason: str = ""
    robots_txt_status: str = "Allowed"
    
    # HTML specific SEO attributes
    title: str = ""
    title_len: int = 0
    meta_description: str = ""
    meta_desc_len: int = 0
    h1_count: int = 0
    h1_first: str = ""
    h2_count: int = 0
    canonical_url: str = ""
    canonical_status: str = "OK"
    meta_robots: str = ""
    x_robots_tag: str = ""
    word_count: int = 0
    has_schema: bool = False
    schema_types: List[str] = field(default_factory=list)
    og_title: str = ""
    og_image: str = ""
    
    # Image specific attributes
    image_alt_text: str = ""
    image_alt_status: str = ""
    
    # Tracking
    sample_parent_url: str = ""
    outlinks_internal_count: int = 0
    outlinks_external_count: int = 0
    issues: List[str] = field(default_factory=list)

class DatabaseManager:
    """Handles high-speed SQLite operations in WAL mode with batching."""
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self.init_db()

    def init_db(self):
        cursor = self.conn.cursor()
        cursor.execute("PRAGMA journal_mode = WAL;")
        cursor.execute("PRAGMA synchronous = NORMAL;")
        cursor.execute("PRAGMA temp_store = MEMORY;")
        cursor.execute("PRAGMA cache_size = -64000;")  # 64MB cache

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS resources (
                url TEXT PRIMARY KEY,
                resource_type TEXT,
                status_code INTEGER,
                status_message TEXT,
                size_bytes INTEGER DEFAULT 0,
                ttfb_ms REAL DEFAULT 0.0,
                crawl_depth INTEGER DEFAULT 0,
                redirect_target TEXT,
                is_internal INTEGER DEFAULT 1,
                indexability TEXT DEFAULT 'Indexable',
                indexability_reason TEXT,
                robots_txt_status TEXT DEFAULT 'Allowed',
                title TEXT,
                title_len INTEGER DEFAULT 0,
                meta_description TEXT,
                meta_desc_len INTEGER DEFAULT 0,
                h1_count INTEGER DEFAULT 0,
                h1_first TEXT,
                h2_count INTEGER DEFAULT 0,
                canonical_url TEXT,
                canonical_status TEXT,
                meta_robots TEXT,
                x_robots_tag TEXT,
                word_count INTEGER DEFAULT 0,
                has_schema INTEGER DEFAULT 0,
                schema_types TEXT,
                og_title TEXT,
                og_image TEXT,
                image_alt_text TEXT,
                image_alt_status TEXT,
                sample_parent_url TEXT,
                outlinks_internal INTEGER DEFAULT 0,
                outlinks_external INTEGER DEFAULT 0,
                issues TEXT
            );
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS inlinks (
                source_url TEXT,
                target_url TEXT,
                resource_type TEXT,
                context TEXT
            );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_inlinks_target ON inlinks(target_url);")
        self.conn.commit()

    def insert_resources_batch(self, resources: List[ResourceRecord]):
        if not resources:
            return
        cursor = self.conn.cursor()
        sql = """
            INSERT OR REPLACE INTO resources (
                url, resource_type, status_code, status_message, size_bytes,
                ttfb_ms, crawl_depth, redirect_target, is_internal, indexability,
                indexability_reason, robots_txt_status, title, title_len,
                meta_description, meta_desc_len, h1_count, h1_first, h2_count,
                canonical_url, canonical_status, meta_robots, x_robots_tag,
                word_count, has_schema, schema_types, og_title, og_image,
                image_alt_text, image_alt_status, sample_parent_url,
                outlinks_internal, outlinks_external, issues
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """
        rows = [
            (
                r.url, r.resource_type, r.status_code, r.status_message, r.size_bytes,
                r.ttfb_ms, r.crawl_depth, r.redirect_target or "", 1 if r.is_internal else 0,
                r.indexability, r.indexability_reason, r.robots_txt_status,
                r.title, r.title_len, r.meta_description, r.meta_desc_len,
                r.h1_count, r.h1_first, r.h2_count, r.canonical_url, r.canonical_status,
                r.meta_robots, r.x_robots_tag, r.word_count, 1 if r.has_schema else 0,
                ", ".join(r.schema_types), r.og_title, r.og_image,
                r.image_alt_text, r.image_alt_status, r.sample_parent_url,
                r.outlinks_internal_count, r.outlinks_external_count, "; ".join(r.issues)
            )
            for r in resources
        ]
        cursor.executemany(sql, rows)
        self.conn.commit()

    def insert_inlinks_batch(self, inlinks: List[Tuple[str, str, str, str]]):
        if not inlinks:
            return
        cursor = self.conn.cursor()
        cursor.executemany("INSERT INTO inlinks (source_url, target_url, resource_type, context) VALUES (?, ?, ?, ?);", inlinks)
        self.conn.commit()

    def get_inlink_counts_map(self) -> Dict[str, int]:
        """Aggregate inlink count per target URL efficiently."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT target_url, COUNT(*) FROM inlinks GROUP BY target_url;")
        return dict(cursor.fetchall())

    def close(self):
        self.conn.close()

class UniversalCrawler:
    def __init__(
        self,
        seed_url: str,
        max_pages: int = 100000,
        max_depth: int = 12,
        concurrency: int = 20,
        timeout: float = 12.0,
        user_agent: str = "UniversalSEOCrawler/2.0 (+https://github.com/universal-crawler)",
        output_file: str = "./master_audit_report.csv",
        crawl_external_assets: bool = True,
        delay_seconds: float = 0.0,
        keep_db: bool = False
    ):
        self.seed_url = clean_url(seed_url)
        self.max_pages = max_pages
        self.max_depth = max_depth
        self.concurrency = concurrency
        self.timeout = timeout
        self.user_agent = user_agent
        self.output_file = Path(output_file)
        self.crawl_external_assets = crawl_external_assets
        self.delay = delay_seconds
        self.keep_db = keep_db

        parsed_seed = urlparse(self.seed_url)
        self.seed_domain = parsed_seed.netloc
        self.seed_scheme = parsed_seed.scheme

        # Database Setup
        self.db_path = self.output_file.parent / f"crawl_cache_{int(time.time())}.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db = DatabaseManager(self.db_path)

        # In-memory frontier queue for ultra-fast async dispatching
        self.queue: Optional[asyncio.Queue[Tuple[str, int, str, Optional[str]]]] = None
        self.queued_urls: Set[str] = set()
        self.crawled_urls: Set[str] = set()

        # Batch buffers for DB flushing
        self.resource_buffer: List[ResourceRecord] = []
        self.inlink_buffer: List[Tuple[str, str, str, str]] = []
        self.buffer_lock = asyncio.Lock()

        # Robots.txt
        self.robot_parser = urllib.robotparser.RobotFileParser()
        self.robots_loaded = False

        # Metrics
        self.start_time = 0.0
        self.pages_crawled_count = 0
        self.active_workers = 0
        self.status_distribution: Dict[str, int] = {"2xx": 0, "3xx": 0, "4xx": 0, "5xx": 0, "Error": 0}
        self.interrupted = False

    def is_internal(self, url: str) -> bool:
        netloc = urlparse(url).netloc
        return netloc == self.seed_domain or netloc.endswith("." + self.seed_domain)

    async def init_robots(self, client: httpx.AsyncClient):
        robots_url = f"{self.seed_scheme}://{self.seed_domain}/robots.txt"
        try:
            resp = await client.get(robots_url, timeout=5.0)
            if resp.status_code == 200:
                self.robot_parser.parse(resp.text.splitlines())
                self.robots_loaded = True
        except Exception:
            pass

    def is_allowed_by_robots(self, url: str) -> bool:
        if not self.robots_loaded:
            return True
        try:
            return self.robot_parser.can_fetch(self.user_agent, url)
        except Exception:
            return True

    def register_inlink(self, source_url: str, target_url: str, resource_type: str, context: str):
        self.inlink_buffer.append((source_url, target_url, resource_type, context))

    async def flush_buffers(self, force: bool = False):
        res_to_flush = []
        inl_to_flush = []
        async with self.buffer_lock:
            if force or len(self.resource_buffer) >= 200:
                res_to_flush = self.resource_buffer[:]
                self.resource_buffer.clear()
            if force or len(self.inlink_buffer) >= 1000:
                inl_to_flush = self.inlink_buffer[:]
                self.inlink_buffer.clear()

        if res_to_flush:
            self.db.insert_resources_batch(res_to_flush)
        if inl_to_flush:
            self.db.insert_inlinks_batch(inl_to_flush)

    async def fetch_resource(self, client: httpx.AsyncClient, url: str, depth: int, parent_url: str, alt_context: Optional[str] = None) -> Optional[ResourceRecord]:
        rdata = ResourceRecord(
            url=url,
            crawl_depth=depth,
            sample_parent_url=parent_url,
            is_internal=self.is_internal(url)
        )

        if alt_context is not None:
            rdata.image_alt_text = alt_context
            rdata.image_alt_status = "Present" if alt_context.strip() else "Empty Decorative"

        headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"
        }

        t0 = time.perf_counter()
        try:
            async with client.stream("GET", url, headers=headers, follow_redirects=True, timeout=self.timeout) as resp:
                rdata.ttfb_ms = round((time.perf_counter() - t0) * 1000.0, 1)
                rdata.status_code = resp.status_code
                rdata.status_message = resp.reason_phrase or str(resp.status_code)
                rdata.content_type = resp.headers.get("content-type", "").split(";")[0].strip()
                rdata.x_robots_tag = resp.headers.get("x-robots-tag", "").strip()

                if len(resp.history) > 0:
                    rdata.redirect_target = str(resp.url)

                rdata.resource_type = guess_resource_type(str(resp.url), rdata.content_type)

                # Memory safe read
                if rdata.resource_type == "HTML":
                    await resp.aread()
                    rdata.size_bytes = len(resp.content)
                else:
                    cl = resp.headers.get("content-length")
                    if cl and cl.isdigit():
                        rdata.size_bytes = int(cl)
                    else:
                        await resp.aread()
                        rdata.size_bytes = len(resp.content)

                # Tally status codes
                if 200 <= resp.status_code < 300:
                    self.status_distribution["2xx"] += 1
                elif 300 <= resp.status_code < 400:
                    self.status_distribution["3xx"] += 1
                elif 400 <= resp.status_code < 500:
                    self.status_distribution["4xx"] += 1
                elif resp.status_code >= 500:
                    self.status_distribution["5xx"] += 1

                if resp.status_code >= 400:
                    rdata.issues.append(f"[CRITICAL: HTTP {resp.status_code}]")
                    rdata.indexability = "Non-Indexable"
                    rdata.indexability_reason = f"HTTP {resp.status_code}"
                    return rdata

                if rdata.resource_type == "HTML" and resp.status_code == 200:
                    try:
                        self.parse_html_page(resp.text, rdata, str(resp.url), depth)
                    except Exception as e:
                        rdata.issues.append(f"[WARNING: Parse Error: {str(e)[:30]}]")

        except httpx.TimeoutException:
            rdata.status_code = 0
            rdata.status_message = "Timeout"
            rdata.issues.append("[CRITICAL: Request Timeout]")
            rdata.indexability = "Non-Indexable"
            rdata.indexability_reason = "Connection Timeout"
            self.status_distribution["Error"] += 1
        except httpx.TooManyRedirects:
            rdata.status_code = 310
            rdata.status_message = "Too Many Redirects"
            rdata.issues.append("[CRITICAL: Redirect Loop Detected]")
            rdata.indexability = "Non-Indexable"
            rdata.indexability_reason = "Redirect Loop"
            self.status_distribution["Error"] += 1
        except Exception as e:
            rdata.status_code = 0
            rdata.status_message = type(e).__name__
            rdata.issues.append(f"[CRITICAL: {type(e).__name__}]")
            rdata.indexability = "Non-Indexable"
            rdata.indexability_reason = type(e).__name__
            self.status_distribution["Error"] += 1

        return rdata

    def parse_html_page(self, html: str, rdata: ResourceRecord, base_url: str, current_depth: int):
        soup = BeautifulSoup(html, "lxml")
        is_https_page = base_url.startswith("https://")

        # --- 1. Title Tag ---
        titles = soup.find_all("title")
        if len(titles) > 1:
            rdata.issues.append(f"[WARNING: Multiple Title Tags ({len(titles)})]")
        if titles and titles[0].get_text(strip=True):
            rdata.title = titles[0].get_text(strip=True)
            rdata.title_len = len(rdata.title)
            if rdata.title_len < 30:
                rdata.issues.append("[WARNING: Title < 30 chars]")
            elif rdata.title_len > 60:
                rdata.issues.append("[WARNING: Title > 60 chars]")
        else:
            rdata.issues.append("[CRITICAL: Missing Title Tag]")

        # --- 2. Meta Description ---
        meta_desc = soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
        if meta_desc and meta_desc.get("content"):
            rdata.meta_description = meta_desc["content"].strip()
            rdata.meta_desc_len = len(rdata.meta_description)
            if rdata.meta_desc_len < 70:
                rdata.issues.append("[WARNING: Meta Description < 70 chars]")
            elif rdata.meta_desc_len > 160:
                rdata.issues.append("[WARNING: Meta Description > 160 chars]")
        else:
            rdata.issues.append("[WARNING: Missing Meta Description]")

        # --- 3. Canonical Tag ---
        canonicals = soup.find_all("link", attrs={"rel": "canonical"})
        if len(canonicals) > 1:
            rdata.issues.append(f"[CRITICAL: Multiple Canonical Tags ({len(canonicals)})]")
        if canonicals and canonicals[0].get("href"):
            raw_canonical = canonicals[0]["href"].strip()
            rdata.canonical_url = urljoin(base_url, raw_canonical)
            cleaned_canon = clean_url(rdata.canonical_url)
            cleaned_curr = clean_url(base_url)
            if cleaned_canon == cleaned_curr:
                rdata.canonical_status = "Self-Referencing"
            else:
                rdata.canonical_status = "Canonicalised"
                rdata.issues.append("[NOTICE: Canonical points to another URL]")
        else:
            rdata.canonical_status = "Missing"
            rdata.issues.append("[WARNING: Missing Canonical Tag]")

        # --- 4. Meta Robots & Googlebot ---
        meta_robots_tags = soup.find_all("meta", attrs={"name": re.compile(r"^(robots|googlebot)$", re.I)})
        for tag in meta_robots_tags:
            content = tag.get("content", "").strip().lower()
            if content:
                rdata.meta_robots = (rdata.meta_robots + ", " + content).strip(", ")
                if "noindex" in content:
                    rdata.indexability = "Non-Indexable"
                    rdata.indexability_reason = f"Meta {tag.get('name')}: noindex"
                    rdata.issues.append(f"[NOTICE: {tag.get('name')} noindex]")

        if "noindex" in rdata.x_robots_tag.lower():
            rdata.indexability = "Non-Indexable"
            rdata.indexability_reason = "X-Robots-Tag: noindex"
            rdata.issues.append("[NOTICE: X-Robots-Tag noindex]")

        if not self.is_allowed_by_robots(base_url):
            rdata.robots_txt_status = "Disallowed"
            rdata.indexability = "Non-Indexable"
            rdata.indexability_reason = "Blocked by robots.txt"
            rdata.issues.append("[WARNING: Blocked by robots.txt]")

        # --- 5. Headings (H1 & H2) ---
        h1s = soup.find_all("h1")
        rdata.h1_count = len(h1s)
        if rdata.h1_count == 0:
            rdata.issues.append("[CRITICAL: Missing H1 Tag]")
        elif rdata.h1_count > 1:
            rdata.issues.append(f"[WARNING: Multiple H1 Tags ({rdata.h1_count})]")
            rdata.h1_first = h1s[0].get_text(strip=True)
        else:
            rdata.h1_first = h1s[0].get_text(strip=True)

        rdata.h2_count = len(soup.find_all("h2"))

        # --- 6. Structured Data (Schema.org JSON-LD) ---
        ld_scripts = soup.find_all("script", attrs={"type": "application/ld+json"})
        if ld_scripts:
            rdata.has_schema = True
            found_types = set()
            for s in ld_scripts:
                try:
                    if s.string:
                        data = json.loads(s.string)
                        if isinstance(data, dict):
                            t = data.get("@type")
                            if t:
                                if isinstance(t, list):
                                    found_types.update(t)
                                else:
                                    found_types.add(str(t))
                            if "@graph" in data and isinstance(data["@graph"], list):
                                for item in data["@graph"]:
                                    if isinstance(item, dict) and "@type" in item:
                                        found_types.add(str(item["@type"]))
                        elif isinstance(data, list):
                            for item in data:
                                if isinstance(item, dict) and "@type" in item:
                                    found_types.add(str(item["@type"]))
                except Exception:
                    pass
            rdata.schema_types = list(found_types)

        # --- 7. OpenGraph Tags ---
        og_t = soup.find("meta", property="og:title")
        if og_t and og_t.get("content"):
            rdata.og_title = og_t["content"].strip()
        og_i = soup.find("meta", property="og:image")
        if og_i and og_i.get("content"):
            rdata.og_image = urljoin(base_url, og_i["content"].strip())

        # ==========================================================
        # EXTRACT ALL ASSETS & ENQUEUE
        # ==========================================================

        # A. Images (<img src>, <img srcset>, <picture><source srcset>)
        for img in soup.find_all(["img", "source"]):
            raw_src = img.get("src") or img.get("data-src")
            srcset = img.get("srcset")
            src_list = []
            if raw_src:
                src_list.append(raw_src)
            if srcset:
                for part in srcset.split(","):
                    chunk = part.strip().split(" ")[0]
                    if chunk:
                        src_list.append(chunk)

            alt_val = img.get("alt")
            for s in src_list:
                img_url = clean_url(urljoin(base_url, s))
                if is_valid_http_url(img_url):
                    if is_https_page and img_url.startswith("http://") and "[WARNING: Insecure Mixed Content (HTTP on HTTPS)]" not in rdata.issues:
                        rdata.issues.append("[WARNING: Insecure Mixed Content (HTTP on HTTPS)]")
                    self.register_inlink(base_url, img_url, "Image", alt_val or "[Image]")
                    self.enqueue_if_new(img_url, current_depth + 1, base_url, alt_context=alt_val)

        # B. JavaScript (<script src>)
        for script in soup.find_all("script", src=True):
            js_url = clean_url(urljoin(base_url, script["src"]))
            if is_valid_http_url(js_url):
                if is_https_page and js_url.startswith("http://") and "[WARNING: Insecure Mixed Content (HTTP on HTTPS)]" not in rdata.issues:
                    rdata.issues.append("[WARNING: Insecure Mixed Content (HTTP on HTTPS)]")
                self.register_inlink(base_url, js_url, "JavaScript", "[Script Tag]")
                self.enqueue_if_new(js_url, current_depth + 1, base_url)

        # C. CSS Stylesheets (<link rel="stylesheet">)
        for link in soup.find_all("link", href=True):
            rel = [r.lower() for r in link.get("rel", [])] if isinstance(link.get("rel"), list) else [str(link.get("rel", "")).lower()]
            css_url = clean_url(urljoin(base_url, link["href"]))
            if not is_valid_http_url(css_url):
                continue

            if "stylesheet" in rel:
                if is_https_page and css_url.startswith("http://") and "[WARNING: Insecure Mixed Content (HTTP on HTTPS)]" not in rdata.issues:
                    rdata.issues.append("[WARNING: Insecure Mixed Content (HTTP on HTTPS)]")
                self.register_inlink(base_url, css_url, "CSS", "[Stylesheet Tag]")
                self.enqueue_if_new(css_url, current_depth + 1, base_url)
            elif "icon" in rel or "apple-touch-icon" in rel:
                self.register_inlink(base_url, css_url, "Image", "[Favicon/Icon]")
                self.enqueue_if_new(css_url, current_depth + 1, base_url)
            elif "preload" in rel:
                as_attr = link.get("as", "").lower()
                rtype = "Font" if as_attr == "font" else "Asset"
                self.register_inlink(base_url, css_url, rtype, f"[Preload as {as_attr}]")
                self.enqueue_if_new(css_url, current_depth + 1, base_url)

        # D. Hyperlinks (<a href>)
        for a in soup.find_all("a", href=True):
            raw_href = a["href"].strip()
            href = clean_url(urljoin(base_url, raw_href))
            if not is_valid_http_url(href):
                continue

            anchor_text = a.get_text(strip=True) or "[Empty Anchor]"
            is_internal = self.is_internal(href)

            if is_internal:
                rdata.outlinks_internal_count += 1
                rtype = guess_resource_type(href)
                self.register_inlink(base_url, href, rtype, anchor_text)
                self.enqueue_if_new(href, current_depth + 1, base_url)
            else:
                rdata.outlinks_external_count += 1
                if self.crawl_external_assets:
                    rtype = guess_resource_type(href)
                    self.register_inlink(base_url, href, rtype, anchor_text)
                    self.enqueue_if_new(href, current_depth + 1, base_url, is_external=True)

        # --- 8. Word Count (Non-destructive text extraction) ---
        body = soup.find("body") or soup
        body_text_chunks = [
            text for text in body.stripped_strings
            if text.parent.name not in ("script", "style", "noscript", "svg", "template")
        ]
        visible_text = " ".join(body_text_chunks)
        words = re.findall(r"\b\w+\b", visible_text)
        rdata.word_count = len(words)
        if rdata.word_count < 200:
            rdata.issues.append("[WARNING: Thin Content (<200 words)]")

    def enqueue_if_new(self, url: str, depth: int, parent_url: str, is_external: bool = False, alt_context: Optional[str] = None):
        if not url or url in self.queued_urls or url in self.crawled_urls:
            return

        if depth > self.max_depth:
            return

        if is_external and not self.crawl_external_assets:
            return

        # Safe limit for queued URLs in memory (keeps memory under 50MB)
        if len(self.queued_urls) >= self.max_pages * 3:
            return

        self.queued_urls.add(url)
        self.queue.put_nowait((url, depth, parent_url, alt_context))

    async def worker(self, worker_id: int, client: httpx.AsyncClient):
        while not self.interrupted:
            try:
                url, depth, parent, alt_context = await asyncio.wait_for(self.queue.get(), timeout=1.5)
            except asyncio.TimeoutError:
                if self.active_workers == 0 and self.queue.empty():
                    break
                continue

            if url in self.crawled_urls:
                self.queue.task_done()
                continue

            self.crawled_urls.add(url)
            self.active_workers += 1

            try:
                if self.delay > 0:
                    await asyncio.sleep(self.delay)

                rdata = await self.fetch_resource(client, url, depth, parent, alt_context)
                if rdata:
                    self.resource_buffer.append(rdata)
                    self.pages_crawled_count += 1
                    await self.flush_buffers()

            finally:
                self.active_workers -= 1
                self.queue.task_done()

            if self.pages_crawled_count >= self.max_pages:
                break

    async def run_crawl(self):
        self.start_time = time.time()
        self.queue = asyncio.Queue()

        limits = httpx.Limits(max_keepalive_connections=self.concurrency, max_connections=self.concurrency * 2)
        async with httpx.AsyncClient(limits=limits, verify=False) as client:
            await self.init_robots(client)
            self.enqueue_if_new(self.seed_url, depth=0, parent_url="[Seed URL]")

            workers = [
                asyncio.create_task(self.worker(i, client))
                for i in range(self.concurrency)
            ]

            with Live(self.render_dashboard(), refresh_per_second=4, console=console) as live:
                while any(not w.done() for w in workers):
                    live.update(self.render_dashboard())
                    await asyncio.sleep(0.25)
                    if self.pages_crawled_count >= self.max_pages:
                        break

                for w in workers:
                    if not w.done():
                        w.cancel()

                live.update(self.render_dashboard(final=True))

        # Flush any remaining items in memory buffers into SQLite
        await self.flush_buffers(force=True)

        # Stream export directly to the single consolidated CSV
        self.export_single_master_csv()

        # Clean up SQLite cache unless requested to keep
        if not self.keep_db:
            self.db.close()
            try:
                if self.db_path.exists():
                    self.db_path.unlink()
                wal = self.db_path.with_name(self.db_path.name + "-wal")
                shm = self.db_path.with_name(self.db_path.name + "-shm")
                if wal.exists(): wal.unlink()
                if shm.exists(): shm.unlink()
            except Exception:
                pass
        else:
            self.db.close()

    def render_dashboard(self, final: bool = False) -> Panel:
        elapsed = max(time.time() - self.start_time, 0.1)
        speed = self.pages_crawled_count / elapsed

        status_style = "bold green" if final else "bold cyan"
        title = f"[{status_style}]⚡ Enterprise SEO Crawler (100k+ Scale) [{'COMPLETE' if final else 'RUNNING'}][/{status_style}]"

        stats_table = Table.grid(padding=(0, 2))
        stats_table.add_column("Key", style="bold white")
        stats_table.add_column("Value", style="yellow")
        stats_table.add_column("Key2", style="bold white")
        stats_table.add_column("Value2", style="yellow")

        q_size = self.queue.qsize() if self.queue else 0
        stats_table.add_row("Seed Domain:", self.seed_domain, "Time Elapsed:", f"{elapsed:.1f}s")
        stats_table.add_row("Total Crawled:", f"{self.pages_crawled_count:,}", "Crawl Speed:", f"{speed:.1f} URLs/sec")
        stats_table.add_row("Frontier Queue:", f"{q_size:,}", "Unique Discovered:", f"{len(self.queued_urls):,}")

        status_line = (
            f"[green]2xx: {self.status_distribution['2xx']:,}[/green]  |  "
            f"[yellow]3xx: {self.status_distribution['3xx']:,}[/yellow]  |  "
            f"[red]4xx: {self.status_distribution['4xx']:,}[/red]  |  "
            f"[bold red]5xx: {self.status_distribution['5xx']:,}[/bold red]  |  "
            f"[bold magenta]Errors: {self.status_distribution['Error']:,}[/bold magenta]"
        )

        content = Table.grid(padding=(1, 0))
        content.add_row(stats_table)
        content.add_row(Panel(status_line, title="HTTP Status Codes", border_style="dim"))
        return Panel(content, title=title, border_style="green" if final else "blue")

    def export_single_master_csv(self):
        """Stream export from SQLite into a single consolidated master CSV file."""
        console.print(f"\n[bold green]💾 Streaming {self.pages_crawled_count:,} records into single master CSV...[/bold green]")
        self.output_file.parent.mkdir(parents=True, exist_ok=True)

        console.print("  [dim]Aggregating internal inlink counts...[/dim]")
        inlinks_map = self.db.get_inlink_counts_map()

        headers = [
            "URL", "Resource Type", "Status Code", "Status Message", "Redirect Target",
            "Size (KB)", "TTFB (ms)", "Crawl Depth", "Inlinks Count", "Discovered On (Parent URL)",
            "Indexability", "Indexability Reason", "Robots.txt Status", "Canonical URL",
            "Canonical Status", "Meta Robots", "X-Robots-Tag", "Title", "Title Length",
            "Meta Description", "Meta Description Length", "H1 Count", "First H1 Text",
            "H2 Count", "Word Count", "Image Alt Text", "Image Alt Status", "Image Size Warning",
            "Has Schema JSON-LD", "Schema Types", "OG Title", "OG Image", "Issues & Warnings"
        ]

        total_exported = 0
        cursor = self.db.conn.cursor()
        cursor.execute("SELECT * FROM resources;")

        with open(self.output_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(headers)

            while True:
                rows = cursor.fetchmany(5000)
                if not rows:
                    break

                for row in rows:
                    url = row[0]
                    rtype = row[1]
                    status_code = row[2]
                    status_msg = row[3]
                    size_bytes = row[4]
                    ttfb_ms = row[5]
                    crawl_depth = row[6]
                    redirect_target = row[7]
                    indexability = row[9]
                    indexability_reason = row[10]
                    robots_txt = row[11]
                    title = row[12]
                    title_len = row[13]
                    meta_desc = row[14]
                    meta_desc_len = row[15]
                    h1_count = row[16]
                    h1_first = row[17]
                    h2_count = row[18]
                    canonical_url = row[19]
                    canonical_status = row[20]
                    meta_robots = row[21]
                    x_robots = row[22]
                    word_count = row[23]
                    has_schema = "Yes" if row[24] == 1 else "No"
                    schema_types = row[25]
                    og_title = row[26]
                    og_image = row[27]
                    img_alt = row[28]
                    img_alt_status = row[29]
                    sample_parent = row[30]
                    issues_str = row[33]

                    inlinks_count = inlinks_map.get(url, 0)
                    size_kb = round(size_bytes / 1024, 1)

                    # Size warning
                    img_size_warning = "OK"
                    if rtype == "Image":
                        if size_kb > 1024:
                            img_size_warning = "CRITICAL > 1MB"
                        elif size_kb > 100:
                            img_size_warning = "WARNING > 100KB"

                    writer.writerow([
                        url, rtype, status_code if status_code is not None else "Err",
                        status_msg, redirect_target or "", size_kb, ttfb_ms, crawl_depth,
                        inlinks_count, sample_parent or "", indexability, indexability_reason or "",
                        robots_txt, canonical_url or "", canonical_status or "",
                        meta_robots or "", x_robots or "", title or "", title_len,
                        meta_desc or "", meta_desc_len, h1_count, h1_first or "",
                        h2_count, word_count, img_alt or "", img_alt_status or "",
                        img_size_warning, has_schema, schema_types or "",
                        og_title or "", og_image or "", issues_str or ""
                    ])
                    total_exported += 1

        console.print(f"[bold green]✨ Successfully exported {total_exported:,} URLs into 1 file:[/bold green] {self.output_file.resolve()}\n")

def main():
    parser = argparse.ArgumentParser(
        description="Universal All-Resource Website Crawler & SEO Audit Engine (100k+ Scale)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument("url", help="Target seed URL (e.g., https://example.com)")
    parser.add_argument("--max-pages", "-m", type=int, default=100000, help="Maximum total resources to crawl (e.g. 100000)")
    parser.add_argument("--max-depth", "-d", type=int, default=12, help="Maximum crawl depth from seed")
    parser.add_argument("--concurrency", "-c", type=int, default=20, help="Number of concurrent workers (15-30 recommended for scale)")
    parser.add_argument("--timeout", "-t", type=float, default=12.0, help="HTTP request timeout in seconds")
    parser.add_argument("--output", "-o", default="./master_audit_report.csv", help="Destination path for single master CSV file")
    parser.add_argument("--delay", type=float, default=0.0, help="Politeness delay between requests in seconds")
    parser.add_argument("--no-external-assets", action="store_true", help="Do not check external CDN images or scripts")
    parser.add_argument("--keep-db", action="store_true", help="Keep the SQLite database cache on disk after CSV export")

    args = parser.parse_args()

    crawler = UniversalCrawler(
        seed_url=args.url,
        max_pages=args.max_pages,
        max_depth=args.max_depth,
        concurrency=args.concurrency,
        timeout=args.timeout,
        output_file=args.output,
        crawl_external_assets=not args.no_external_assets,
        delay_seconds=args.delay,
        keep_db=args.keep_db
    )

    def handle_sigint(sig, frame):
        console.print("\n[bold yellow]⚠️ Crawl interrupted by user! Flushing SQLite and saving single CSV...[/bold yellow]")
        crawler.interrupted = True
        try:
            crawler.db.insert_resources_batch(crawler.resource_buffer)
            crawler.db.insert_inlinks_batch(crawler.inlink_buffer)
            if crawler.pages_crawled_count > 0:
                crawler.export_single_master_csv()
        except Exception as e:
            console.print(f"[red]Error during emergency export: {e}[/red]")
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_sigint)

    try:
        asyncio.run(crawler.run_crawl())
    except KeyboardInterrupt:
        handle_sigint(None, None)

if __name__ == "__main__":
    main()
