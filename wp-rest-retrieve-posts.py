#!/usr/bin/env python3
"""Fetch posts, pages, and custom post types from a WordPress site via the REST API and save as Markdown.

Writes incrementally — one file per item as each API page completes. Supports checkpoint/resume.
Uses curl_cffi for TLS fingerprint matching (bypasses Cloudflare bot management).

Usage: ./wp-rest-retrieve-posts.py <site-url> [--type <types>] [--output <dir>] [--per-page <n>] [--delay <seconds>]

Examples:
    ./wp-rest-retrieve-posts.py https://www.example.com
    ./wp-rest-retrieve-posts.py https://www.example.com --type posts pages
    ./wp-rest-retrieve-posts.py https://www.example.com --type all --delay 20
    ./wp-rest-retrieve-posts.py https://www.example.com --type posts pages my_custom_type
"""

import os
import re
import subprocess
import sys

_DEPS = ["html2text", "pyyaml", "requests", "curl_cffi"]
_DIR = os.path.dirname(os.path.abspath(__file__))
_VENV = os.path.join(_DIR, ".venv")
_VENV_PYTHON = os.path.join(_VENV, "bin", "python3")

# Bootstrap: create venv and install deps on first run, then re-exec
if os.path.realpath(sys.executable) != os.path.realpath(_VENV_PYTHON):
    if not os.path.exists(_VENV_PYTHON):
        print("First run — setting up environment...")
        import venv
        venv.create(_VENV, with_pip=True)
        subprocess.check_call([_VENV_PYTHON, "-m", "pip", "install", "-q"] + _DEPS)
        print("Done.\n")
    else:
        # Ensure all deps are installed (covers newly added packages)
        subprocess.check_call(
            [_VENV_PYTHON, "-m", "pip", "install", "-q"] + _DEPS,
            stdout=subprocess.DEVNULL,
        )
    os.execv(_VENV_PYTHON, [_VENV_PYTHON] + sys.argv)

import argparse
import html
import random
import time

from urllib.parse import urlparse

import html2text
import requests
import yaml

try:
    from curl_cffi.requests import Session as CffiSession
    session = CffiSession(impersonate="chrome")
except ImportError:
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    })

converter = html2text.HTML2Text()
converter.body_width = 0
converter.ignore_images = False
converter.ignore_links = False


# ---------------------------------------------------------------------------
# Progress tracking (checkpoint/resume) — pattern from importer-sitemap-parser
# ---------------------------------------------------------------------------

def load_progress(path):
    """Read a progress file. Returns (done_urls set, last_completed_page int)."""
    if not os.path.exists(path):
        return set(), 0
    done = set()
    last_page = 0
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("PAGE:"):
                last_page = int(line.split(":")[1])
            elif line:
                done.add(line)
    return done, last_page


def save_progress(path, url):
    """Append a single completed URL to the progress file."""
    with open(path, "a", encoding="utf-8") as f:
        f.write(url + "\n")


def save_page_progress(path, page):
    """Mark a page as fully completed in the progress file."""
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"PAGE:{page}\n")


def throttle(delay):
    """Sleep with randomized jitter (±25%) to look human."""
    jitter = delay * 0.25
    time.sleep(delay + random.uniform(-jitter, jitter))


def _request_with_retry(url, params=None, timeout=60, stream=False):
    """GET request with retry (3 attempts, 15/30/45s backoff)."""
    for attempt in range(3):
        try:
            resp = session.get(url, params=params, timeout=timeout, stream=stream)
            return resp
        except Exception as e:
            if attempt < 2:
                wait = (attempt + 1) * 15
                print(f"    Retry {attempt + 1}/3 after {wait}s — {e}", flush=True)
                time.sleep(wait)
            else:
                raise
    return None


def fetch_pages(endpoint, per_page, delay, start_page=1):
    """Yield (page_num, batch, total, total_pages) for each page of a paginated WP REST API endpoint."""
    page = start_page

    while True:
        print(f"  Fetching page {page}...", flush=True)
        resp = _request_with_retry(endpoint, params={"per_page": per_page, "page": page})

        if resp.status_code == 400:
            break
        resp.raise_for_status()

        batch = resp.json()
        if not batch:
            break

        total = int(resp.headers.get("X-WP-Total", 0))
        total_pages = int(resp.headers.get("X-WP-TotalPages", 0))
        yield page, batch, total, total_pages

        if page >= total_pages:
            break

        page += 1
        throttle(delay)


def fetch_all_items(endpoint, per_page, delay):
    """Fetch all items from a paginated WP REST API endpoint (collects in memory)."""
    items = []
    for _page, batch, _total, _total_pages in fetch_pages(endpoint, per_page, delay):
        items.extend(batch)
    return items


def build_taxonomy_map(base_url, taxonomy, per_page, delay):
    """Fetch all terms for a taxonomy and return an {id: name} dict."""
    endpoint = f"{base_url}/wp-json/wp/v2/{taxonomy}"
    items = fetch_all_items(endpoint, per_page, delay)
    return {item["id"]: html.unescape(item["name"]) for item in items}


def build_media_map(base_url, media_ids, per_page, delay):
    """Batch-fetch media metadata and return {media_id: source_url}."""
    media_map = {}
    ids = list(media_ids)
    for i in range(0, len(ids), per_page):
        chunk = ids[i:i + per_page]
        include = ",".join(str(mid) for mid in chunk)
        try:
            resp = _request_with_retry(
                f"{base_url}/wp-json/wp/v2/media",
                params={"include": include, "per_page": per_page},
            )
            resp.raise_for_status()
            for item in resp.json():
                source = item.get("source_url")
                if source:
                    media_map[item["id"]] = source
        except Exception as e:
            print(f"  Warning: failed to fetch media chunk — {e}", file=sys.stderr, flush=True)
        if i + per_page < len(ids):
            throttle(delay)
    return media_map


def download_images(media_map, images_dir, delay):
    """Download images to disk. Returns {media_id: local_filename}. Skips existing files."""
    from urllib.parse import unquote as _unquote
    os.makedirs(images_dir, exist_ok=True)
    result = {}
    used_filenames = set()
    for mid, source_url in media_map.items():
        filename = _unquote(urlparse(source_url).path.rsplit("/", 1)[-1])
        if filename in used_filenames:
            name, ext = os.path.splitext(filename)
            filename = f"{mid}-{name}{ext}"
        used_filenames.add(filename)

        filepath = os.path.join(images_dir, filename)
        if os.path.exists(filepath):
            print(f"  Skipping (exists): {filename}", flush=True)
            result[mid] = filename
            continue

        try:
            resp = _request_with_retry(source_url, stream=True)
            resp.raise_for_status()
            with open(filepath, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            print(f"  Downloaded: {filename}", flush=True)
            result[mid] = filename
        except Exception as e:
            print(f"  Warning: failed to download {source_url} — {e}", file=sys.stderr, flush=True)
        throttle(delay)
    return result


def probe_api(base_url):
    """Probe the WP REST API root and return the response JSON, or exit with a clear error."""
    url = f"{base_url}/wp-json/"
    try:
        resp = session.get(url, timeout=30)
    except Exception as e:
        print(f"Error: Could not connect to {base_url} — {e}", file=sys.stderr)
        sys.exit(1)

    content_type = resp.headers.get("content-type", "")
    if resp.status_code != 200 or "application/json" not in content_type:
        print(f"Error: {base_url} does not appear to have a WordPress REST API.", file=sys.stderr)
        sys.exit(1)

    try:
        data = resp.json()
    except ValueError:
        print(f"Error: {base_url} does not appear to have a WordPress REST API.", file=sys.stderr)
        sys.exit(1)

    if "namespaces" not in data or "routes" not in data:
        print(f"Error: {base_url} does not appear to have a WordPress REST API.", file=sys.stderr)
        sys.exit(1)

    print(f"Site: {data.get('name', base_url)}", flush=True)
    return data


def _listable_rest_bases(routes):
    """Extract rest_bases that have a simple listable GET route under /wp/v2/."""
    bases = set()
    for route_pattern, route_info in routes.items():
        # Match routes like /wp/v2/posts but not /wp/v2/posts/(?P<id>[\d]+)
        m = re.match(r"^/wp/v2/([a-zA-Z0-9_-]+)$", route_pattern)
        if not m:
            continue
        for endpoint in route_info.get("endpoints", []):
            if "GET" in endpoint.get("methods", []):
                bases.add(m.group(1))
                break
    return bases


def discover_post_types(base_url, root_data):
    """Discover content types using routes from the root response and /types metadata.

    Only returns types whose rest_base has a simple listable route in /wp/v2/.
    """
    listable = _listable_rest_bases(root_data.get("routes", {}))

    resp = session.get(f"{base_url}/wp-json/wp/v2/types", timeout=30)
    resp.raise_for_status()
    types = resp.json()

    result = []
    for slug, info in types.items():
        rest_base = info.get("rest_base", slug)
        if rest_base not in listable:
            continue
        result.append({
            "slug": slug,
            "rest_base": rest_base,
            "name": info.get("name", slug),
            "taxonomies": info.get("taxonomies", []),
        })
    return result


def post_to_markdown(post, category_map, tag_map, post_type_slug="post", image_context=None):
    """Convert a single WP post/page/CPT JSON object to a Markdown string with YAML frontmatter."""
    title_obj = post.get("title", {})
    title = html.unescape(title_obj.get("rendered", "")) if isinstance(title_obj, dict) else str(title_obj)
    date = post.get("date", "")[:10]
    link = post.get("link", "")
    content_obj = post.get("content", {})
    content_html = content_obj.get("rendered", "") if isinstance(content_obj, dict) else str(content_obj)
    content_md = converter.handle(content_html).strip() if content_html else ""

    frontmatter = {"title": title, "date": date, "url": link, "type": post_type_slug}

    featured_media = post.get("featured_media", 0)
    if featured_media:
        if image_context and featured_media in image_context:
            ctx = image_context[featured_media]
            frontmatter["featured_image"] = ctx.get("local_path") or ctx.get("source_url")
        else:
            frontmatter["featured_media_id"] = featured_media

    categories = [category_map[cid] for cid in post.get("categories", []) if cid in category_map]
    if categories:
        frontmatter["categories"] = categories

    tags = [tag_map[tid] for tid in post.get("tags", []) if tid in tag_map]
    if tags:
        frontmatter["tags"] = tags

    fm_str = yaml.dump(frontmatter, sort_keys=False, allow_unicode=True, default_flow_style=False).rstrip()
    return f"---\n{fm_str}\n---\n\n{content_md}"


def main():
    parser = argparse.ArgumentParser(description="Export WordPress posts, pages, and custom post types to Markdown via the REST API.")
    parser.add_argument("url", help="WordPress site URL (e.g. https://www.example.com)")
    parser.add_argument("--type", "-t", nargs="+", default=["posts"], dest="types",
                        help="Post types to export by REST base name (default: posts). Use 'all' to auto-discover.")
    parser.add_argument("--output", "-o", default=None, help="Output directory (default: <domain>-articles)")
    parser.add_argument("--per-page", type=int, default=100, help="Posts per API request (default: 100)")
    parser.add_argument("--delay", type=float, default=18, help="Seconds between requests (default: 18)")
    parser.add_argument("--images", action="store_true", help="Download featured images locally")
    parser.add_argument("--cookie", default=None, help="Cookie string to bypass bot protection (e.g. 'name=value; name2=value2')")
    args = parser.parse_args()

    if args.cookie:
        for pair in args.cookie.split(";"):
            pair = pair.strip()
            if "=" in pair:
                k, v = pair.split("=", 1)
                session.cookies.set(k.strip(), v.strip())

    base_url = args.url.rstrip("/")

    print("Note: This tool is for exporting content you own or have permission to use.", flush=True)
    print("      Respect copyright and the site's terms of service.\n", flush=True)

    # Probe the REST API before doing anything else
    root_data = probe_api(base_url)

    domain = urlparse(base_url).hostname.replace("www.", "")

    # Output directory (--split is now the default behavior for incremental writes)
    output_dir = args.output or f"{domain}-articles"
    os.makedirs(output_dir, exist_ok=True)

    # --- Resolve post types ---
    if "all" in args.types:
        print(f"Discovering post types on {base_url}...", flush=True)
        type_list = discover_post_types(base_url, root_data)
        if not type_list:
            print("No content types found.", file=sys.stderr)
            sys.exit(1)
        print(f"  Found types: {', '.join(t['rest_base'] for t in type_list)}\n", flush=True)
    else:
        _WELL_KNOWN = {
            "posts": {"slug": "post", "rest_base": "posts", "name": "Posts", "taxonomies": ["category", "post_tag"]},
            "pages": {"slug": "page", "rest_base": "pages", "name": "Pages", "taxonomies": []},
        }

        # Only fetch /types if the user requested a non-well-known type
        unknown = [t for t in args.types if t not in _WELL_KNOWN]
        if unknown:
            print(f"Fetching type metadata from {base_url}...", flush=True)
            resp = session.get(f"{base_url}/wp-json/wp/v2/types", timeout=30)
            resp.raise_for_status()
            all_types = resp.json()
            for slug, info in all_types.items():
                rb = info.get("rest_base", slug)
                _WELL_KNOWN[rb] = {
                    "slug": slug, "rest_base": rb,
                    "name": info.get("name", slug),
                    "taxonomies": info.get("taxonomies", []),
                }

        type_list = []
        for requested in args.types:
            if requested in _WELL_KNOWN:
                type_list.append(_WELL_KNOWN[requested])
            else:
                print(f"Warning: unknown post type '{requested}' — skipping.", file=sys.stderr, flush=True)

        if not type_list:
            print("No valid post types to export.", file=sys.stderr)
            sys.exit(1)

    # --- Fetch taxonomy maps upfront (small, needed for markdown rendering) ---
    needs_categories = any("category" in t.get("taxonomies", []) for t in type_list)
    needs_tags = any("post_tag" in t.get("taxonomies", []) for t in type_list)

    category_map = {}
    tag_map = {}

    if needs_categories:
        print("Fetching categories...", flush=True)
        category_map = build_taxonomy_map(base_url, "categories", per_page=100, delay=args.delay)
        print(f"  {len(category_map)} categories found.", flush=True)
        throttle(args.delay)

    if needs_tags:
        print("Fetching tags...", flush=True)
        tag_map = build_taxonomy_map(base_url, "tags", per_page=100, delay=args.delay)
        print(f"  {len(tag_map)} tags found.\n", flush=True)
        throttle(args.delay)

    # --- Pull each type incrementally ---
    multi_type = len(type_list) > 1
    total_written = 0

    for type_info in type_list:
        slug = type_info["slug"]
        rest_base = type_info["rest_base"]
        taxonomies = type_info["taxonomies"]
        cats = category_map if "category" in taxonomies else {}
        tags = tag_map if "post_tag" in taxonomies else {}

        # Set up output directory and progress file
        if multi_type:
            type_dir = os.path.join(output_dir, rest_base)
        else:
            type_dir = output_dir
        os.makedirs(type_dir, exist_ok=True)
        progress_file = os.path.join(output_dir, f".progress-{rest_base}")
        done_urls, last_page = load_progress(progress_file)
        start_page = last_page + 1 if last_page else 1

        if done_urls:
            print(f"Resuming {rest_base} — {len(done_urls)} already done, starting at page {start_page}.", flush=True)

        endpoint = f"{base_url}/wp-json/wp/v2/{rest_base}"
        print(f"\nPulling {type_info['name'].lower()} ({rest_base})...", flush=True)

        type_written = 0
        first_page = True

        for page_num, batch, total, total_pages in fetch_pages(endpoint, args.per_page, args.delay, start_page=start_page):
            if first_page:
                print(f"  Total: {total} items across {total_pages} pages", flush=True)
                first_page = False

            for item in batch:
                link = item.get("link", "")
                if link in done_urls:
                    continue

                title_obj = item.get("title", {})
                title_raw = title_obj.get("rendered", "") if isinstance(title_obj, dict) else str(title_obj)
                item_slug = item.get("slug") or re.sub(r"[^\w-]", "", title_raw.lower().replace(" ", "-"))
                date = item["date"][:10]
                filename = os.path.join(type_dir, f"{date}-{item_slug}.md")

                md = post_to_markdown(item, cats, tags, post_type_slug=slug)
                with open(filename, "w", encoding="utf-8") as f:
                    f.write(md)
                    f.write("\n")

                save_progress(progress_file, link)
                type_written += 1

            save_page_progress(progress_file, page_num)

        print(f"  Written {type_written} new files to {type_dir}/", flush=True)
        total_written += type_written

    # --- Resolve featured media URLs ---
    # Scan written files for featured_media_id, batch-fetch source URLs
    media_ids = set()
    md_files_with_media = []
    for root, dirs, files in os.walk(output_dir):
        for f in files:
            if not f.endswith(".md"):
                continue
            filepath = os.path.join(root, f)
            with open(filepath, "r", encoding="utf-8") as fh:
                head = fh.read(1000)
            m = re.search(r"featured_media_id:\s*(\d+)", head)
            if m:
                mid = int(m.group(1))
                media_ids.add(mid)
                md_files_with_media.append((filepath, mid))

    if media_ids:
        print(f"\nResolving {len(media_ids)} featured media URLs...", flush=True)
        media_map = build_media_map(base_url, media_ids, per_page=100, delay=args.delay)
        print(f"  {len(media_map)} source URLs resolved.", flush=True)

        image_local_map = {}
        if args.images:
            images_dir = os.path.join(output_dir, "images")
            print(f"Downloading images to {images_dir}/...", flush=True)
            image_local_map = download_images(media_map, images_dir, args.delay)
            print(f"  {len(image_local_map)} images downloaded.", flush=True)

        # Update frontmatter in written files
        updated = 0
        for filepath, mid in md_files_with_media:
            if mid not in media_map:
                continue
            source_url = media_map[mid]
            image_ref = f"images/{image_local_map[mid]}" if mid in image_local_map else source_url

            with open(filepath, "r", encoding="utf-8") as fh:
                content = fh.read()
            content = content.replace(
                f"featured_media_id: {mid}",
                f"featured_image: {image_ref}",
            )
            with open(filepath, "w", encoding="utf-8") as fh:
                fh.write(content)
            updated += 1
        print(f"  Updated {updated} files with image references.", flush=True)

    # Clean up progress files on full completion
    for type_info in type_list:
        pf = os.path.join(output_dir, f".progress-{type_info['rest_base']}")
        if os.path.exists(pf):
            os.remove(pf)

    print(f"\nDone. {total_written} total files written to {output_dir}/", flush=True)


if __name__ == "__main__":
    main()
