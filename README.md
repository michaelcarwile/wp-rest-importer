# WP REST Importer

A toolkit for working with WordPress content via the REST API. Currently supports pulling posts from any public WordPress site and exporting them as clean Markdown.

## Quick Start

### Requirements

- Python 3
- `html2text` and `requests` packages

### Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install html2text requests
```

### Usage

```bash
# Basic — auto-names output as <domain>-articles.md
python3 wp-rest-retrieve-posts.py https://www.example.com

# Custom output file
python3 wp-rest-retrieve-posts.py https://www.example.com -o my-posts.md

# Adjust pagination and rate limiting
python3 wp-rest-retrieve-posts.py https://www.example.com --per-page 20 --delay 2
```

The script fetches all posts, converts HTML to Markdown, and writes them to a single file sorted by date (oldest first), separated by horizontal rules.

## Files

| File | Status | Description |
|------|--------|-------------|
| `wp-rest-retrieve-posts.py` | Active | Fetches posts from a WordPress site and exports to Markdown |
| `wp-rest-tools.php` | Future | PHP-based tools for importing/publishing content to WordPress |

## Roadmap

- [ ] Publish/import downloaded articles into another WordPress site
- [ ] Support for pages and custom post types (not just posts)
- [ ] Category and tag preservation in export
- [ ] Featured image downloading
- [ ] Authenticated API access for private/draft posts
