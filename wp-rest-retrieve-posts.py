#!/usr/bin/env python3
"""Fetch all posts from a WordPress site via the REST API and save as a single Markdown file.

Usage: ./wp-rest-retrieve-posts.py <site-url> [--output <file>] [--per-page <n>] [--delay <seconds>]

Examples:
    ./wp-rest-retrieve-posts.py https://www.example.com
    ./wp-rest-retrieve-posts.py https://www.example.com --output articles.md --per-page 20
"""

import os
import subprocess
import sys

_DEPS = ["html2text", "requests"]
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
    os.execv(_VENV_PYTHON, [_VENV_PYTHON] + sys.argv)

import argparse
import html
import time

import html2text
import requests

converter = html2text.HTML2Text()
converter.body_width = 0
converter.ignore_images = False
converter.ignore_links = False


def fetch_all_posts(endpoint, per_page, delay):
    """Fetch all posts, paginating through the API."""
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


def post_to_markdown(post):
    """Convert a single WP post JSON object to a Markdown string."""
    title = html.unescape(post["title"]["rendered"])
    date = post["date"][:10]
    link = post["link"]
    content_html = post["content"]["rendered"]
    content_md = converter.handle(content_html).strip()

    return f"# {title}\n\n**Date:** {date}  \n**URL:** {link}\n\n{content_md}"


def main():
    parser = argparse.ArgumentParser(description="Export WordPress posts to a single Markdown file via the REST API.")
    parser.add_argument("url", help="WordPress site URL (e.g. https://www.example.com)")
    parser.add_argument("--output", "-o", default=None, help="Output filename (default: <domain>-articles.md)")
    parser.add_argument("--per-page", type=int, default=10, help="Posts per API request (default: 10)")
    parser.add_argument("--delay", type=float, default=1, help="Seconds between requests (default: 1)")
    args = parser.parse_args()

    base_url = args.url.rstrip("/")
    endpoint = f"{base_url}/wp-json/wp/v2/posts"

    # Derive default output filename from domain
    if args.output:
        output_file = args.output
    else:
        from urllib.parse import urlparse
        domain = urlparse(base_url).hostname.replace("www.", "")
        output_file = f"{domain}-articles.md"

    print(f"Fetching articles from {base_url}...")
    posts = fetch_all_posts(endpoint, args.per_page, args.delay)

    if not posts:
        print("No posts found.", file=sys.stderr)
        sys.exit(1)

    print(f"Fetched {len(posts)} articles.\n")

    posts.sort(key=lambda p: p["date"])
    sections = [post_to_markdown(p) for p in posts]

    with open(output_file, "w", encoding="utf-8") as f:
        f.write("\n\n---\n\n".join(sections))
        f.write("\n")

    print(f"Written to {output_file}")


if __name__ == "__main__":
    main()
