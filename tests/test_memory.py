from tests.support import *

from unittest.mock import patch
import shlex

from init_agent.agent_tools import repo_memory_add
from init_agent.memory import add_note, list_notes, update_note, with_live_staleness
from init_agent.mcp_tools import _handle_repo_memory_update
from init_agent.session_tools import repo_session_close
from init_agent.web_ui import build_web_snapshot


class MemoryEvidenceTests(InitAgentTestCase):
    def test_session_suggests_executable_revalidation_without_a_map(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            path = "src/auth/session.py"
            added = repo_memory_add(root, path, "Session validation lives here.")
            self.assertFalse(added["memory"]["stale"])
            self.assertFalse(any("stale until" in warning for warning in added["warnings"]))
            (root / path).write_text("def validateSession(): return False\n")
            close = repo_session_close(root)
            suggestion = next(item for item in close["suggested_memory"] if item["kind"] == "refresh_stale_memory")
            args = shlex.split(suggestion["command"])
            self.assertIn("--revalidate", args)
            args[args.index("<updated-note>")] = "Session validation now returns False."
            previous = Path.cwd()
            try:
                os.chdir(root)
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(args[1:]), 0)
                updated = json.loads(output.getvalue())["memory"]
                self.assertFalse(updated["stale"])
                self.assertEqual(updated["id"], added["memory"]["id"])
            finally:
                os.chdir(previous)
            with GraphStore(root) as store:
                self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM files").fetchone()[0], 0)

    def test_metadata_edits_do_not_revalidate_changed_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            _prepare_index(root)
            path = "src/auth/session.py"
            with patch("init_agent.memory.utc_now", return_value="2020-01-01T00:00:00+00:00"):
                original = add_note(root, path, "Session validation.")
            (root / path).write_text("def validateSession(): return False\n")
            for change in ({}, {"tags": ["session"]}, {"topic": "auth"}, {"note": "Reworded note."}):
                with self.subTest(change=change):
                    note = _handle_repo_memory_update(root, {"id": original["id"], **change})["memory"]
                    self.assertTrue(note["stale"])
                    self.assertEqual(note["file_sha256"], original["file_sha256"])
                    self.assertEqual(note["created_at"], original["created_at"])
            fresh = _handle_repo_memory_update(root, {"id": original["id"], "revalidate": True})["memory"]
            self.assertFalse(fresh["stale"])
            self.assertEqual(fresh["file_sha256"], fresh["current_file_sha256"])
            self.assertNotEqual(fresh["created_at"], original["created_at"])
            with self.assertRaises(ValueError):
                _handle_repo_memory_update(root, {"id": original["id"], "revalidate": "false"})
            (root / path).unlink()
            with self.assertRaises(ValueError):
                update_note(root, original["id"], revalidate=True)
            self.assertEqual(list_notes(root)[0]["file_sha256"], fresh["file_sha256"])

    def test_dashboard_staleness_matches_memory_without_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            _prepare_index(root)
            path = "src/auth/session.py"
            original = add_note(root, path, "Session validation.")
            add_note(root, None, "Project decision.", scope="repo")
            unindexed = root / ".new.py"
            unindexed.write_text("VALUE = 1\n")
            add_note(root, ".new.py", "New file outside the last map.")
            legacy = add_note(root, "README.md", "Old note.")
            with GraphStore(root) as store:
                store.connection.execute("UPDATE agent_notes SET file_sha256 = NULL WHERE id = ?", (legacy["id"],))
                store.connection.commit()
            database = root / ".agent" / "graph.sqlite"
            before = database.read_bytes()

            def compare() -> dict:
                expected = {note["id"]: note for note in list_notes(root)}
                actual = {note["id"]: note for note in build_web_snapshot(root)["recent_memory"]}
                for note_id in expected:
                    for key in ("stale", "stale_reason", "current_file_sha256"):
                        self.assertEqual(actual[note_id][key], expected[note_id][key])
                return actual

            self.assertFalse(compare()[original["id"]]["stale"])
            (root / path).write_text("def validateSession(): return False\n")
            self.assertTrue(compare()[original["id"]]["stale"])
            (root / path).unlink()
            self.assertTrue(compare()[original["id"]]["stale"])
            self.assertEqual(database.read_bytes(), before)

    def test_live_staleness_hashes_duplicate_paths_once_and_rejects_external_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            outside = Path(tmp) / "outside.py"
            outside.write_text("VALUE = 1\n")
            (root / "link.py").symlink_to(outside)
            notes = [{"path": "link.py", "scope": "file", "file_sha256": "old"}] * 2
            with patch("init_agent.memory.sha256_file") as hasher:
                self.assertTrue(all(note["stale"] for note in with_live_staleness(root, notes)))
                hasher.assert_not_called()
            with patch("init_agent.memory._current_file_sha256", return_value="old") as hasher:
                self.assertTrue(all(note["stale"] is False for note in with_live_staleness(root, notes)))
                hasher.assert_called_once_with(root, "link.py")
