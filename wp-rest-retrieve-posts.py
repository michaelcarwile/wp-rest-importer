#!/usr/bin/env python3
"""Fetch all posts from a WordPress site via the REST API and save as a single Markdown file.

Usage: ./wp-rest-retrieve-posts.py <site-url> [--output <file>] [--per-page <n>] [--delay <seconds>]

Examples:
    ./wp-rest-retrieve-posts.py https://www.example.com
    ./wp-rest-retrieve-posts.py https://www.example.com --output articles.md --per-page 20
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

        if resp.status_code == 400:
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


def post_to_markdown(post, category_map, tag_map):
    """Convert a single WP post JSON object to a Markdown string with YAML frontmatter."""
    title = html.unescape(post["title"]["rendered"])
    date = post["date"][:10]
    link = post["link"]
    content_html = post["content"]["rendered"]
    content_md = converter.handle(content_html).strip()

    frontmatter = {"title": title, "date": date, "url": link}

    categories = [category_map[cid] for cid in post.get("categories", []) if cid in category_map]
    if categories:
        frontmatter["categories"] = categories

    tags = [tag_map[tid] for tid in post.get("tags", []) if tid in tag_map]
    if tags:
        frontmatter["tags"] = tags

    fm_str = yaml.dump(frontmatter, sort_keys=False, allow_unicode=True, default_flow_style=False).rstrip()
    return f"---\n{fm_str}\n---\n\n{content_md}"


def main():
    parser = argparse.ArgumentParser(description="Export WordPress posts to a single Markdown file via the REST API.")
    parser.add_argument("url", help="WordPress site URL (e.g. https://www.example.com)")
    parser.add_argument("--output", "-o", default=None, help="Output filename (default: <domain>-articles.md)")
    parser.add_argument("--per-page", type=int, default=20, help="Posts per API request (default: 20)")
    parser.add_argument("--delay", type=float, default=3, help="Seconds between requests (default: 3)")
    parser.add_argument("--split", action="store_true", help="Write one Markdown file per post into an output directory")
    args = parser.parse_args()

    base_url = args.url.rstrip("/")
    endpoint = f"{base_url}/wp-json/wp/v2/posts"

    from urllib.parse import urlparse
    domain = urlparse(base_url).hostname.replace("www.", "")

    # Derive default output path from domain
    if args.split:
        output_dir = args.output or f"{domain}-articles"
    else:
        output_file = args.output or f"{domain}-articles.md"

    print(f"Fetching articles from {base_url}...")
    posts = fetch_all_items(endpoint, args.per_page, args.delay)

    if not posts:
        print("No posts found.", file=sys.stderr)
        sys.exit(1)

    print(f"Fetched {len(posts)} articles.\n")

    print("Fetching categories...")
    category_map = build_taxonomy_map(base_url, "categories", per_page=100, delay=args.delay)
    print(f"  {len(category_map)} categories found.")

    print("Fetching tags...")
    tag_map = build_taxonomy_map(base_url, "tags", per_page=100, delay=args.delay)
    print(f"  {len(tag_map)} tags found.\n")

    posts.sort(key=lambda p: p["date"])
    sections = [post_to_markdown(p, category_map, tag_map) for p in posts]

    if args.split:
        os.makedirs(output_dir, exist_ok=True)
        for i, (post, md) in enumerate(zip(posts, sections), 1):
            slug = post.get("slug") or re.sub(r"[^\w-]", "", post["title"]["rendered"].lower().replace(" ", "-"))
            date = post["date"][:10]
            filename = os.path.join(output_dir, f"{date}-{slug}.md")
            with open(filename, "w", encoding="utf-8") as f:
                f.write(md)
                f.write("\n")
        print(f"Written {len(sections)} files to {output_dir}/")
    else:
        with open(output_file, "w", encoding="utf-8") as f:
            f.write("\n\n".join(sections))
            f.write("\n")
        print(f"Written to {output_file}")


if __name__ == "__main__":
    main()
