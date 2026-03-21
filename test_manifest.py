"""Unit tests for manifest tracking functions in wp-rest-retrieve-posts.py."""

import json
import os
import tempfile
import unittest

# Import the module's manifest functions directly
# We can't import the module normally because of the venv bootstrap,
# so we parse and exec just the functions we need.
import importlib.util
import sys
import types

def _load_functions():
    """Load manifest functions from the script without triggering the venv bootstrap."""
    script = os.path.join(os.path.dirname(__file__), "wp-rest-retrieve-posts.py")
    with open(script, "r") as f:
        source = f.read()

    # Create a minimal module with required imports
    mod = types.ModuleType("wp_rest")
    mod.__file__ = script
    exec("import os, json, re\nfrom datetime import datetime, timezone", mod.__dict__)

    # Extract and exec each function we need
    import ast
    tree = ast.parse(source)
    func_names = {
        "_now_iso", "load_manifest", "save_manifest", "get_type_state",
        "update_type_state", "_migrate_progress_files", "init_manifest",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in func_names:
            func_source = ast.get_source_segment(source, node)
            exec(func_source, mod.__dict__)
    return mod


mod = _load_functions()


class TestManifestFunctions(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir)

    def test_load_manifest_empty(self):
        result = mod.load_manifest(self.tmpdir)
        self.assertEqual(result, {})

    def test_save_and_load_manifest(self):
        manifest = {
            "domain": "example.com",
            "base_url": "https://example.com",
            "status": "in_progress",
            "types": {},
        }
        mod.save_manifest(self.tmpdir, manifest)

        # File should exist
        path = os.path.join(self.tmpdir, "manifest.json")
        self.assertTrue(os.path.exists(path))

        # Temp file should NOT exist
        self.assertFalse(os.path.exists(path + ".tmp"))

        # Load it back
        loaded = mod.load_manifest(self.tmpdir)
        self.assertEqual(loaded["domain"], "example.com")
        self.assertIn("updated_at", loaded)

    def test_get_type_state_missing(self):
        manifest = {"types": {"posts": {"status": "complete"}}}
        self.assertIsNone(mod.get_type_state(manifest, "pages"))
        self.assertEqual(mod.get_type_state(manifest, "posts")["status"], "complete")

    def test_get_type_state_no_types_key(self):
        self.assertIsNone(mod.get_type_state({}, "posts"))

    def test_update_type_state_creates(self):
        manifest = {}
        mod.update_type_state(manifest, "posts", status="in_progress", last_page=3)
        self.assertEqual(manifest["types"]["posts"]["status"], "in_progress")
        self.assertEqual(manifest["types"]["posts"]["last_page"], 3)

    def test_update_type_state_updates(self):
        manifest = {"types": {"posts": {"status": "in_progress", "last_page": 2}}}
        mod.update_type_state(manifest, "posts", last_page=5, items_written=250)
        self.assertEqual(manifest["types"]["posts"]["last_page"], 5)
        self.assertEqual(manifest["types"]["posts"]["items_written"], 250)
        self.assertEqual(manifest["types"]["posts"]["status"], "in_progress")

    def test_migrate_progress_files(self):
        # Create a legacy progress file
        pf = os.path.join(self.tmpdir, ".progress-posts")
        with open(pf, "w") as f:
            f.write("https://example.com/post-1/\n")
            f.write("https://example.com/post-2/\n")
            f.write("PAGE:1\n")
            f.write("https://example.com/post-3/\n")
            f.write("https://example.com/post-4/\n")
            f.write("PAGE:2\n")

        type_list = [{"slug": "post", "rest_base": "posts", "name": "Posts", "taxonomies": []}]
        manifest = mod._migrate_progress_files(self.tmpdir, type_list)

        # Should have migrated
        self.assertIn("posts", manifest["types"])
        ts = manifest["types"]["posts"]
        self.assertEqual(ts["last_page"], 2)
        self.assertEqual(ts["items_written"], 4)
        self.assertEqual(ts["status"], "in_progress")

        # Legacy file should be deleted
        self.assertFalse(os.path.exists(pf))

        # manifest.json should exist
        self.assertTrue(os.path.exists(os.path.join(self.tmpdir, "manifest.json")))

    def test_migrate_no_progress_files(self):
        type_list = [{"slug": "post", "rest_base": "posts", "name": "Posts", "taxonomies": []}]
        manifest = mod._migrate_progress_files(self.tmpdir, type_list)
        self.assertEqual(manifest, {})

    def test_init_manifest_fresh(self):
        type_list = [{"slug": "post", "rest_base": "posts", "name": "Posts", "taxonomies": []}]
        manifest = mod.init_manifest(self.tmpdir, "example.com", "https://example.com", type_list)

        self.assertEqual(manifest["domain"], "example.com")
        self.assertEqual(manifest["status"], "in_progress")
        self.assertTrue(os.path.exists(os.path.join(self.tmpdir, "manifest.json")))

    def test_init_manifest_existing(self):
        # Pre-create a manifest
        existing = {
            "domain": "example.com",
            "base_url": "https://example.com",
            "status": "in_progress",
            "types": {"posts": {"status": "complete", "items_written": 500}},
        }
        mod.save_manifest(self.tmpdir, existing)

        type_list = [{"slug": "post", "rest_base": "posts", "name": "Posts", "taxonomies": []}]
        manifest = mod.init_manifest(self.tmpdir, "example.com", "https://example.com", type_list)

        # Should load existing, not create new
        self.assertEqual(manifest["types"]["posts"]["status"], "complete")
        self.assertEqual(manifest["types"]["posts"]["items_written"], 500)

    def test_init_manifest_migration(self):
        # Create legacy progress file but no manifest
        pf = os.path.join(self.tmpdir, ".progress-posts")
        with open(pf, "w") as f:
            f.write("https://example.com/a/\nPAGE:1\n")

        type_list = [{"slug": "post", "rest_base": "posts", "name": "Posts", "taxonomies": []}]
        manifest = mod.init_manifest(self.tmpdir, "example.com", "https://example.com", type_list)

        self.assertEqual(manifest["domain"], "example.com")
        self.assertEqual(manifest["types"]["posts"]["last_page"], 1)
        self.assertFalse(os.path.exists(pf))

    def test_atomic_write_no_partial(self):
        """save_manifest should not leave a corrupt file if the dict is valid."""
        manifest = {"domain": "test.com", "types": {}}
        mod.save_manifest(self.tmpdir, manifest)

        # Read raw and parse — should be valid JSON
        path = os.path.join(self.tmpdir, "manifest.json")
        with open(path, "r") as f:
            data = json.load(f)
        self.assertEqual(data["domain"], "test.com")

    def test_complete_workflow(self):
        """Simulate a full pull: init → type in_progress → pages → complete."""
        type_list = [
            {"slug": "post", "rest_base": "posts", "name": "Posts", "taxonomies": []},
            {"slug": "page", "rest_base": "pages", "name": "Pages", "taxonomies": []},
        ]
        manifest = mod.init_manifest(self.tmpdir, "example.com", "https://example.com", type_list)

        # Start posts
        mod.update_type_state(manifest, "posts",
                              status="in_progress", total_items=200, total_pages=2,
                              last_page=0, items_written=0, started_at=mod._now_iso(),
                              completed_at=None)
        mod.save_manifest(self.tmpdir, manifest)

        # Page 1 done
        mod.update_type_state(manifest, "posts", last_page=1, items_written=100)
        mod.save_manifest(self.tmpdir, manifest)

        # Simulate crash & resume — reload
        manifest = mod.load_manifest(self.tmpdir)
        ts = mod.get_type_state(manifest, "posts")
        self.assertEqual(ts["last_page"], 1)
        self.assertEqual(ts["items_written"], 100)
        self.assertEqual(ts["status"], "in_progress")

        # Page 2 done, type complete
        mod.update_type_state(manifest, "posts", last_page=2, items_written=200,
                              status="complete", completed_at=mod._now_iso())
        mod.save_manifest(self.tmpdir, manifest)

        # Pages type
        mod.update_type_state(manifest, "pages",
                              status="complete", total_items=10, total_pages=1,
                              last_page=1, items_written=10,
                              started_at=mod._now_iso(), completed_at=mod._now_iso())
        mod.save_manifest(self.tmpdir, manifest)

        # Check final state
        manifest = mod.load_manifest(self.tmpdir)
        self.assertEqual(manifest["types"]["posts"]["status"], "complete")
        self.assertEqual(manifest["types"]["pages"]["status"], "complete")


if __name__ == "__main__":
    unittest.main()
