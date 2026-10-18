"""Regression cases for domain words and accidental substring matches."""

import tempfile
import unittest
from pathlib import Path

from init_agent.context_builder import build_context_pack
from init_agent.graph_store import GraphStore
from init_agent.scanner import scan_project


class RankingQueryTokensTests(unittest.TestCase):
    def test_skill_queries_retain_the_implementation_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".agent").mkdir()
            (root / "skill_installer.py").write_text("def install():\n    pass\n")
            (root / "rpc.py").write_text("def dispatch():\n    pass\n")
            with GraphStore(root) as store:
                store.initialize()
                scan_project(root, store)
            for query in ("skill", "skills"):
                with self.subTest(query=query):
                    pack = build_context_pack(root, query)
                    self.assertTrue(pack["candidate_files"])
                    self.assertEqual(pack["candidate_files"][0]["path"], "skill_installer.py")

    def test_connectives_do_not_promote_unrelated_symbols(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".agent").mkdir()
            (root / "billing.py").write_text("def validate_invoice():\n    return True\n")
            (root / "feedback.py").write_text("def contribution():\n    return 0\n")
            (root / "rpc.py").write_text("def call_tool():\n    pass\n")
            with GraphStore(root) as store:
                store.initialize()
                scan_project(root, store)
            plain = build_context_pack(root, "validate invoice")
            prose = build_context_pack(root, "validate invoice but validate invoice too")
            self.assertEqual(plain["candidate_files"], prose["candidate_files"])
            self.assertEqual([item["path"] for item in prose["candidate_files"]], ["billing.py"])
