# WP REST Importer

A toolkit for working with WordPress content via the REST API. Currently supports pulling posts from any public WordPress site and exporting them as clean Markdown.

## Quick Start

```bash
./wp-rest-retrieve-posts.py https://www.example.com
```

That's it. On first run, the script automatically creates a virtual environment and installs its dependencies.

### Options

```bash
# Custom output file
./wp-rest-retrieve-posts.py https://www.example.com -o my-posts.md

# Adjust pagination and rate limiting (defaults: 20 posts/request, 3s delay)
./wp-rest-retrieve-posts.py https://www.example.com --per-page 50 --delay 1
```

Output is a single Markdown file with all posts sorted by date (oldest first), separated by horizontal rules.

## Files

| File | Description |
|------|-------------|
| `wp-rest-retrieve-posts.py` | Fetches posts from a WordPress site and exports to Markdown |
| `wp-rest-tools.php` | *(Future)* PHP-based tools for importing/publishing content to WordPress |

## Roadmap

- [ ] Category and tag preservation in export
- [ ] Support for pages and custom post types (not just posts)
- [ ] Featured image downloading
- [ ] Authenticated API access for private/draft posts
- [ ] Publish/import downloaded articles into another WordPress site
