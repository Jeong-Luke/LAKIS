"""Library history retains older files and bounds metadata work per page."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "external_ui"))
import serve_ui


class LibraryPaginationTests(unittest.TestCase):
    def test_all_450_files_and_metadata_survive_paging(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index in range(450):
                path = root / f"image-{index:04}.webp"
                path.write_bytes(b"fixture")
                # Same timestamp exercises the deterministic ID tie breaker.
                os.utime(path, ns=(1_700_000_000_000_000_000,) * 2)
            with mock.patch.object(serve_ui, "_history_roots", return_value=[("configured", root)]), \
                    mock.patch.object(serve_ui, "_image_prompt_metadata", side_effect=lambda p: {"prompt": p.stem}) as metadata:
                ids, cursor = [], None
                while True:
                    before = metadata.call_count
                    page = serve_ui.image_history(limit=100, cursor=cursor)
                    self.assertLessEqual(metadata.call_count - before, 100)
                    for item in page["items"]:
                        self.assertEqual(item["prompt"], Path(item["name"]).stem)
                    ids.extend(item["id"] for item in page["items"])
                    cursor = page["next_cursor"]
                    if cursor is None:
                        break
                self.assertEqual(len(ids), 450)
                self.assertEqual(len(set(ids)), 450)
                self.assertEqual(len(list(root.glob("*.webp"))), 450)

    def test_new_and_deleted_images_do_not_shift_next_page(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index in range(6):
                path = root / f"{index}.png"
                path.write_bytes(b"fixture")
                os.utime(path, ns=(1_700_000_000_000_000_000 + index,) * 2)
            with mock.patch.object(serve_ui, "_history_roots", return_value=[("configured", root)]), \
                    mock.patch.object(serve_ui, "_image_prompt_metadata", return_value={}):
                first = serve_ui.image_history(limit=2)
                (root / "5.png").unlink()
                (root / "new.png").write_bytes(b"newer")
                second = serve_ui.image_history(limit=2, cursor=first["next_cursor"])
                third = serve_ui.image_history(limit=2, cursor=second["next_cursor"])
                self.assertEqual([item["name"] for item in second["items"]], ["3.png", "2.png"])
                self.assertEqual([item["name"] for item in third["items"]], ["1.png", "0.png"])
                self.assertIsNone(third["next_cursor"])

    def test_invalid_cursor_and_limits_rejected(self):
        for cursor in ("bad", "[]", "{}", '[true,"x"]', '[1,2]', '[1,"x",3]'):
            with self.subTest(cursor=cursor), self.assertRaises(ValueError):
                serve_ui.image_history(cursor=cursor)
        for limit in (0, -1, 301):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                serve_ui.image_history(limit=limit)

    def test_empty_library_has_no_next_page(self):
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(serve_ui, "_history_roots", return_value=[("configured", Path(directory))]):
            page = serve_ui.image_history(limit=100)
            self.assertEqual(page["items"], [])
            self.assertIsNone(page["next_cursor"])

    def test_batch_delete_accepts_page_boundary_and_oldest_items(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root, recycled = base / "images", base / "recycled"
            root.mkdir()
            recycled.mkdir()
            for index in range(450):
                path = root / f"image-{index:04}.png"
                path.write_bytes(b"fixture")
                os.utime(path, ns=(1_700_000_000_000_000_000 + index,) * 2)
            with mock.patch.object(serve_ui, "_history_roots", return_value=[("configured", root)]), \
                    mock.patch.object(serve_ui, "_image_prompt_metadata", return_value={}) as metadata, \
                    mock.patch.object(serve_ui, "_send_to_recycle_bin", side_effect=lambda p: p.rename(recycled / p.name)) as recycle:
                pages, cursor = [], None
                for _ in range(5):
                    page = serve_ui.image_history(limit=100, cursor=cursor)
                    pages.append(page["items"])
                    cursor = page["next_cursor"]
                selected = [pages[0][0]["id"], pages[2][-1]["id"],
                            pages[3][0]["id"], pages[4][-1]["id"]]
                metadata.reset_mock()
                result = serve_ui.delete_history_images_batch(selected + [selected[2]])
                self.assertTrue(result["ok"])
                self.assertEqual(result["requested"], 4)
                self.assertEqual(result["deleted_items"], selected)
                self.assertEqual(result["failed"], 0)
                self.assertEqual(recycle.call_count, 4)
                metadata.assert_not_called()
                self.assertEqual(len(list(root.glob("*.png"))), 446)
                self.assertEqual(len(list(recycled.glob("*.png"))), 4)
                self.assertTrue((root / "image-0250.png").is_file())

    def test_batch_delete_preserves_root_checks_and_partial_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            configured, default, recycled = (base / name for name in ("configured", "default", "recycled"))
            for folder in (configured, default, recycled):
                folder.mkdir()
            (configured / "blocked.png").write_bytes(b"keep")
            (configured / "unselected.png").write_bytes(b"keep")
            (configured / "note.txt").write_bytes(b"keep")
            (configured / "directory.png").mkdir()
            (default / "legacy.webp").write_bytes(b"recycle")
            (base / "outside.png").write_bytes(b"keep")

            def recycle(path):
                if path.name == "blocked.png":
                    raise PermissionError("fixture locked image")
                path.rename(recycled / path.name)

            invalid = ["configured:../outside.png", "unknown:legacy.webp",
                       "configured:missing.png", "configured:note.txt", "configured:directory.png"]
            with mock.patch.object(serve_ui, "_history_roots", return_value=[("configured", configured), ("default", default)]), \
                    mock.patch.object(serve_ui, "_image_prompt_metadata") as metadata, \
                    mock.patch.object(serve_ui, "_send_to_recycle_bin", side_effect=recycle):
                result = serve_ui.delete_history_images_batch(["configured:blocked.png", *invalid, "default:legacy.webp"])
            self.assertFalse(result["ok"])
            self.assertEqual(result["deleted_items"], ["default:legacy.webp"])
            self.assertEqual(result["failed"], 6)
            self.assertEqual(result["failed_items"][0]["reason"], "fixture locked image")
            self.assertEqual([item["id"] for item in result["failed_items"][1:]], invalid)
            metadata.assert_not_called()
            for path in (base / "outside.png", configured / "blocked.png",
                         configured / "unselected.png", configured / "note.txt"):
                self.assertEqual(path.read_bytes(), b"keep")
            self.assertTrue((configured / "directory.png").is_dir())
            self.assertEqual((recycled / "legacy.webp").read_bytes(), b"recycle")


if __name__ == "__main__":
    unittest.main()
