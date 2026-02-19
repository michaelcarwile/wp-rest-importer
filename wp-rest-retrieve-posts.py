#!/usr/bin/env python3
"""Fetch posts, pages, and custom post types from a WordPress site via the REST API and save as Markdown.

Usage: ./wp-rest-retrieve-posts.py <site-url> [--type <types>] [--output <file>] [--per-page <n>] [--delay <seconds>]

Examples:
    ./wp-rest-retrieve-posts.py https://www.example.com
    ./wp-rest-retrieve-posts.py https://www.example.com --type pages
    ./wp-rest-retrieve-posts.py https://www.example.com --type posts pages --split
    ./wp-rest-retrieve-posts.py https://www.example.com --type all --delay 1
"""

import os
import re
import subprocess
import sys

_DEPS = ["html2text", "pyyaml", "requests"]
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
import time

import html2text
import requests
import yaml

converter = html2text.HTML2Text()
converter.body_width = 0
converter.ignore_images = False
converter.ignore_links = False


def fetch_all_items(endpoint, per_page, delay):
    """Fetch all items from a paginated WP REST API endpoint."""
    posts = []
    page = 1

    while True:
        print(f"  Fetching page {page}...")
        resp = requests.get(endpoint, params={"per_page": per_page, "page": page}, timeout=30)

        if resp.status_code in (400, 401, 403, 404):
            break
        resp.raise_for_status()

        batch = resp.json()
        if not batch:
            break

        posts.extend(batch)
        total = int(resp.headers.get("X-WP-Total", 0))
        if len(posts) >= total:
            break

        page += 1
        time.sleep(delay)

    return posts


def build_taxonomy_map(base_url, taxonomy, per_page, delay):
    """Fetch all terms for a taxonomy and return an {id: name} dict."""
    endpoint = f"{base_url}/wp-json/wp/v2/{taxonomy}"
    items = fetch_all_items(endpoint, per_page, delay)
    return {item["id"]: html.unescape(item["name"]) for item in items}


_BUILTIN_SKIP = {
    "attachment", "wp_block", "wp_template", "wp_template_part",
    "wp_navigation", "nav_menu_item", "wp_global_styles",
    "wp_font_family", "wp_font_face",
}


def discover_post_types(base_url):
    """Fetch all public post types and return a list of content types (excluding builtins).

    Each entry is a dict with keys: slug, rest_base, name, taxonomies.
    """
    resp = requests.get(f"{base_url}/wp-json/wp/v2/types", timeout=30)
    resp.raise_for_status()
    types = resp.json()
    result = []
    for slug, info in types.items():
        if slug in _BUILTIN_SKIP:
            continue
        rest_base = info.get("rest_base", slug)
        # Skip types with parameterized rest_base (not directly listable)
        if "(" in rest_base:
            continue
        result.append({
            "slug": slug,
            "rest_base": info.get("rest_base", slug),
            "name": info.get("name", slug),
            "taxonomies": info.get("taxonomies", []),
        })
    return result


def post_to_markdown(post, category_map, tag_map, post_type_slug="post"):
    """Convert a single WP post JSON object to a Markdown string with YAML frontmatter."""
    title = html.unescape(post["title"]["rendered"])
    date = post["date"][:10]
    link = post["link"]
    content_html = post.get("content", {}).get("rendered", "")
    content_md = converter.handle(content_html).strip() if content_html else ""

    frontmatter = {"title": title, "date": date, "url": link, "type": post_type_slug}

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
    parser.add_argument("--output", "-o", default=None, help="Output filename (default: <domain>-articles.md)")
    parser.add_argument("--per-page", type=int, default=20, help="Posts per API request (default: 20)")
    parser.add_argument("--delay", type=float, default=3, help="Seconds between requests (default: 3)")
    parser.add_argument("--split", action="store_true", help="Write one Markdown file per post into an output directory")
    args = parser.parse_args()

    base_url = args.url.rstrip("/")

    from urllib.parse import urlparse
    domain = urlparse(base_url).hostname.replace("www.", "")

    # Derive default output path from domain
    if args.split:
        output_dir = args.output or f"{domain}-articles"
    else:
        output_file = args.output or f"{domain}-articles.md"

    # --- Resolve post types ---
    if "all" in args.types:
        print(f"Discovering post types on {base_url}...")
        type_list = discover_post_types(base_url)
        if not type_list:
            print("No content types found.", file=sys.stderr)
            sys.exit(1)
        print(f"  Found types: {', '.join(t['rest_base'] for t in type_list)}\n")
    else:
        # Fetch type metadata to get taxonomy info for requested types
        print(f"Fetching type metadata from {base_url}...")
        resp = requests.get(f"{base_url}/wp-json/wp/v2/types", timeout=30)
        resp.raise_for_status()
        all_types = resp.json()

        # Build lookup by rest_base
        rest_base_lookup = {}
        for slug, info in all_types.items():
            rb = info.get("rest_base", slug)
            rest_base_lookup[rb] = {
                "slug": slug,
                "rest_base": rb,
                "name": info.get("name", slug),
                "taxonomies": info.get("taxonomies", []),
            }

        type_list = []
        for requested in args.types:
            if requested in rest_base_lookup:
                type_list.append(rest_base_lookup[requested])
            else:
                print(f"Warning: unknown post type '{requested}' — skipping.", file=sys.stderr)

        if not type_list:
            print("No valid post types to export.", file=sys.stderr)
            sys.exit(1)

    # --- Fetch content for each type ---
    category_map = None
    tag_map = None
    # Collect (slug, rest_base, item, markdown) tuples
    results = []

    for type_info in type_list:
        slug = type_info["slug"]
        rest_base = type_info["rest_base"]
        taxonomies = type_info["taxonomies"]

        endpoint = f"{base_url}/wp-json/wp/v2/{rest_base}"
        print(f"Fetching {type_info['name'].lower()} ({rest_base})...")
        items = fetch_all_items(endpoint, args.per_page, args.delay)

        if not items:
            print(f"  No {type_info['name'].lower()} found.\n")
            continue
        print(f"  Fetched {len(items)} items.\n")

        # Fetch taxonomy maps on demand (at most once each)
        if "category" in taxonomies and category_map is None:
            print("Fetching categories...")
            category_map = build_taxonomy_map(base_url, "categories", per_page=100, delay=args.delay)
            print(f"  {len(category_map)} categories found.")
        if "post_tag" in taxonomies and tag_map is None:
            print("Fetching tags...")
            tag_map = build_taxonomy_map(base_url, "tags", per_page=100, delay=args.delay)
            print(f"  {len(tag_map)} tags found.\n")

        cats = category_map if ("category" in taxonomies and category_map) else {}
        tags = tag_map if ("post_tag" in taxonomies and tag_map) else {}

        for item in items:
            md = post_to_markdown(item, cats, tags, post_type_slug=slug)
            results.append((slug, rest_base, item, md))

    if not results:
        print("No content found across any type.", file=sys.stderr)
        sys.exit(1)

    # --- Write output ---
    multi_type = len(type_list) > 1

    if args.split:
        os.makedirs(output_dir, exist_ok=True)
        for _slug, rest_base, item, md in results:
            item_slug = item.get("slug") or re.sub(r"[^\w-]", "", item["title"]["rendered"].lower().replace(" ", "-"))
            date = item["date"][:10]
            if multi_type:
                subdir = os.path.join(output_dir, rest_base)
                os.makedirs(subdir, exist_ok=True)
                filename = os.path.join(subdir, f"{date}-{item_slug}.md")
            else:
                filename = os.path.join(output_dir, f"{date}-{item_slug}.md")
            with open(filename, "w", encoding="utf-8") as f:
                f.write(md)
                f.write("\n")
        print(f"Written {len(results)} files to {output_dir}/")
    else:
        # Group by type in request order, sorted by date within each group
        from collections import OrderedDict
        groups = OrderedDict()
        for _slug, rest_base, item, md in results:
            groups.setdefault(rest_base, []).append((item["date"], md))
        sections = []
        for rest_base, entries in groups.items():
            entries.sort(key=lambda e: e[0])
            sections.extend(md for _date, md in entries)
        with open(output_file, "w", encoding="utf-8") as f:
            f.write("\n\n".join(sections))
            f.write("\n")
        print(f"Written to {output_file}")


if __name__ == "__main__":
    main()
