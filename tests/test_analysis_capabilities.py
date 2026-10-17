from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from init_agent.graph_store import GraphStore
from init_agent.memory import add_note
from init_agent.refresh import refresh_index
from init_agent.scanner import scan_project
from init_agent.utils import ensure_agent_dir


class AnalysisCapabilitiesTests(unittest.TestCase):
    def _scan(self, root: Path) -> None:
        ensure_agent_dir(root)
        with GraphStore(root) as store:
            store.initialize()
            scan_project(root, store)

    def test_persists_structural_and_regex_fallback_capabilities(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "valid.py").write_text("def hello():\n    return 1\n")
            (root / "broken.py").write_text("def hello(:\n    return 1\n")
            self._scan(root)
            with GraphStore(root) as store:
                rows = store.connection.execute(
                    "SELECT files.path, file_analysis.metadata_json FROM files "
                    "JOIN file_analysis ON files.id=file_analysis.file_id"
                ).fetchall()
                values = {row["path"]: json.loads(row["metadata_json"]) for row in rows}
                symbols = store.connection.execute(
                    "SELECT COUNT(*) AS n FROM symbols WHERE file_id=(SELECT id FROM files WHERE path='broken.py')"
                ).fetchone()["n"]
            self.assertTrue(values["valid.py"]["structural"])
            self.assertTrue(values["valid.py"]["text_search"])
            self.assertEqual(values["broken.py"]["analyzer"], "python-regex-fallback")
            self.assertFalse(values["broken.py"]["structural"])
            self.assertGreater(symbols, 0)

    def test_refresh_reindexes_stale_analyzer_without_touching_notes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "main.py"
            source.write_text("def run():\n    pass\n")
            self._scan(root)
            add_note(root, "main.py", "Keep this note through reanalysis")
            with GraphStore(root) as store:
                store.connection.execute(
                    "UPDATE file_analysis SET metadata_json='{}' WHERE file_id=(SELECT id FROM files WHERE path='main.py')"
                )
                store.connection.commit()
            result = refresh_index(root)
            self.assertEqual(result["updated"], ["main.py"])
            with GraphStore(root) as store:
                metadata = json.loads(store.connection.execute("SELECT metadata_json FROM file_analysis").fetchone()[0])
                self.assertTrue(metadata["indexed"])
                note_count = store.connection.execute("SELECT COUNT(*) AS n FROM agent_notes").fetchone()["n"]
                self.assertEqual(note_count, 1)


if __name__ == "__main__":
    unittest.main()
