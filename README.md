# WP REST Importer

A toolkit for working with WordPress content via the REST API. Supports pulling posts, pages, and custom post types from any public WordPress site and exporting them as clean Markdown. The script probes the REST API on startup and fails fast with a clear message if the site doesn't expose one.

## Quick Start

```bash
./wp-rest-retrieve-posts.py https://www.example.com
```

That's it. On first run, the script automatically creates a virtual environment and installs its dependencies.

### Options

```bash
# Custom output file
./wp-rest-retrieve-posts.py https://www.example.com -o my-posts.md

# One file per post (great for AI tools like NotebookLM)
./wp-rest-retrieve-posts.py https://www.example.com --split

# Export pages instead of posts
./wp-rest-retrieve-posts.py https://www.example.com --type pages

# Export both posts and pages (split mode creates subdirectories per type)
./wp-rest-retrieve-posts.py https://www.example.com --type posts pages --split

# Auto-discover and export all public post types
./wp-rest-retrieve-posts.py https://www.example.com --type all

# Adjust pagination and rate limiting (defaults: 20 posts/request, 3s delay)
./wp-rest-retrieve-posts.py https://www.example.com --per-page 50 --delay 1
```

By default, output is a single Markdown file with all posts sorted by date (oldest first). Use `--split` to write one file per post into a directory instead (default: `<domain>-articles/`). When exporting multiple types with `--split`, files are organized into subdirectories by type (e.g., `posts/`, `pages/`). Each item uses YAML frontmatter for metadata:

```markdown
---
title: "Post Title"
date: 2024-01-15
url: https://example.com/post
type: post
categories:
  - News
tags:
  - python
---

Post content here...
```

Categories and tags are resolved to their names automatically. Keys are omitted when a post has no categories or tags. The `type` field reflects the WordPress post type slug (e.g., `post`, `page`).

## Files

| File | Description |
|------|-------------|
| `wp-rest-retrieve-posts.py` | Fetches posts, pages, and custom post types from a WordPress site and exports to Markdown |
| `wp-rest-tools.php` | *(Future)* PHP-based tools for importing/publishing content to WordPress |

## Roadmap

- [x] Category and tag preservation in export
- [x] Support for pages and custom post types (not just posts)
- [ ] Featured image downloading
- [ ] Authenticated API access for private/draft posts
- [ ] Publish/import downloaded articles into another WordPress site
