# wp-rest-importer

Export WordPress posts, pages, and custom post types to Markdown via the REST API. Supports checkpoint/resume, featured image downloading, and Cloudflare bypass.

## What this is

A CLI toolkit for pulling content from any public WordPress site through its REST API. The primary tool (`wp-rest-retrieve-posts.py`) fetches all content types, converts HTML to Markdown with YAML frontmatter, and writes one file per post. It handles pagination, rate limiting, taxonomy resolution, featured images, and crash recovery via a manifest-based checkpoint system. A secondary PHP script (`wp-rest-tools.php`) provides a simpler XML export path.

## Tech stack

- Python 3 (main export tool, self-bootstrapping venv)
- `curl_cffi` for TLS fingerprint impersonation (Cloudflare bypass)
- `html2text` for HTML-to-Markdown conversion
- `pyyaml` for YAML frontmatter
- `requests` as HTTP fallback
- PHP (secondary XML exporter, uses cURL)
- `unittest` for tests (no external test runner)

## Directory structure

```
wp-rest-retrieve-posts.py   # Main tool: WP REST API -> Markdown export
wp-rest-tools.php           # Secondary tool: WP REST API -> XML export
test_manifest.py            # Unit tests for manifest/checkpoint functions
.gitignore                  # Ignores .venv, __pycache__, output dirs
README.md                   # User-facing docs with examples
```

Output directories (gitignored) created at runtime:

```
<domain>-articles/           # Default output dir (one .md per post)
  manifest.json              # Checkpoint state for resume
  posts/                     # Subdirectory when exporting multiple types
  pages/
  images/                    # Downloaded featured images (--images flag)
```

## How it works

### Self-bootstrapping venv

On first run, the Python script detects it is not running inside its own `.venv`. It creates a venv, installs dependencies (`html2text`, `pyyaml`, `requests`, `curl_cffi`), then re-execs itself under the venv Python. On subsequent runs it just re-execs into the existing venv (and quietly ensures deps are up to date).

### Export pipeline

1. **Probe** -- `probe_api()` hits `/wp-json/` and validates the site exposes a WordPress REST API. Fails fast with a clear message if not.
2. **Discover types** -- `discover_post_types()` queries `/wp-json/wp/v2/types` and cross-references with listable routes from the API root to build an inventory of exportable content types.
3. **Inventory** -- For each type, a HEAD-style request fetches `X-WP-Total` / `X-WP-TotalPages` headers. Results are cached in `manifest.json`.
4. **Interactive selection** -- Unless `--yes` or explicit `--type` is given, the user is prompted to select which types to pull (by number or name).
5. **Taxonomy resolution** -- Categories and tags are batch-fetched into `{id: name}` maps so frontmatter uses human-readable names.
6. **Incremental pull** -- `fetch_pages()` paginates through each type's endpoint. After each API page, files are written to disk and `manifest.json` is updated. This enables crash recovery: on restart, the script resumes from the last completed page.
7. **Featured media** -- After all posts are written, the script scans output files for `featured_media_id` placeholders, batch-resolves media URLs via `/wp/v2/media`, and rewrites frontmatter to `featured_image`. With `--images`, images are downloaded to an `images/` subdirectory.

### Rate limiting

Requests use a configurable delay (default 18s) with +/-25% random jitter. Failed requests retry 3 times with 15/30/45s backoff.

### Cloudflare bypass

`curl_cffi` impersonates Chrome's TLS fingerprint. If the library is unavailable, falls back to `requests` with a spoofed User-Agent. A `--cookie` flag allows passing bot-protection cookies manually.

### PHP exporter (wp-rest-tools.php)

A simpler standalone PHP script that fetches posts via the REST API and writes them to an XML file. No venv, no checkpoint, no taxonomy resolution. Intended as a lightweight alternative or future import tool base.

## Key files

| File | Purpose |
|------|---------|
| `wp-rest-retrieve-posts.py` | Main CLI tool. Handles venv bootstrap, API probing, type discovery, paginated fetch, Markdown conversion, manifest tracking, image downloading. |
| `wp-rest-tools.php` | Secondary PHP-based XML exporter. Simpler, posts-only. |
| `test_manifest.py` | Unit tests for manifest/checkpoint functions. Uses AST parsing to import functions without triggering the venv bootstrap. |
| `.gitignore` | Excludes `.venv/`, `__pycache__/`, and output dirs (`*-articles/`, `*-articles.md`, `*-images/`). |

## Key conventions

- The Python script is a single-file tool -- no package structure, no setup.py
- Venv is auto-managed; users never need to `pip install` manually
- Output is always one Markdown file per post with YAML frontmatter (title, date, url, type, categories, tags, featured_image)
- `manifest.json` is written atomically (write to `.tmp`, then `os.replace`) to prevent corruption on crash
- Filenames follow `<date>-<slug>.md` format
- Multi-type exports organize files into subdirectories by REST base name
- Rate limiting defaults are conservative (18s delay, 100 per page) to avoid triggering bot protection
- Copyright notice is printed on every run

## Tests

```bash
python3 test_manifest.py
```

Tests cover the manifest/checkpoint system: save/load, type state tracking, legacy progress file migration, atomic writes, and a full simulated workflow. Tests use AST extraction to import functions from the main script without triggering the venv bootstrap.

## Usage

```bash
# Basic: export all content types from a site
./wp-rest-retrieve-posts.py https://www.example.com

# Export specific types
./wp-rest-retrieve-posts.py https://www.example.com --type posts pages

# Auto-confirm (skip interactive prompt)
./wp-rest-retrieve-posts.py https://www.example.com --yes

# Download featured images locally
./wp-rest-retrieve-posts.py https://www.example.com --images

# Custom output directory, pagination, and delay
./wp-rest-retrieve-posts.py https://www.example.com -o my-export --per-page 50 --delay 5

# Pass cookies for bot-protected sites
./wp-rest-retrieve-posts.py https://www.example.com --cookie 'cf_clearance=abc123'

# PHP XML exporter
php wp-rest-tools.php --url=https://www.example.com
```
