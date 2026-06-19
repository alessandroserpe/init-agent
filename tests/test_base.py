from __future__ import annotations

import os
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from init_agent.context_builder import build_context_pack
from init_agent.cli import main
from init_agent.doctor import run_doctor
from init_agent.estimate import estimate_tokens
from init_agent.graph_store import GraphStore
from init_agent.refresh import refresh_index
from init_agent.symbol_extractor import extract_symbols_and_relations


class InitAgentBaseTests(unittest.TestCase):
    def test_python_symbol_extraction(self) -> None:
        content = "import os\nfrom pathlib import Path\nclass Runner:\n    pass\ndef run(value):\n    return value\n"
        symbols, relations = extract_symbols_and_relations(content, "python")
        self.assertIn(("Runner", "class"), [(item.name, item.kind) for item in symbols])
        self.assertIn(("run", "function"), [(item.name, item.kind) for item in symbols])
        self.assertIn("os", [item.target for item in relations])
        self.assertIn("pathlib", [item.target for item in relations])

    def test_cli_init_and_map(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text("[project]\nname = 'sample'\n", encoding="utf-8")
            (root / "app.py").write_text("class App:\n    pass\n\ndef main():\n    return App()\n", encoding="utf-8")
            previous = Path.cwd()
            try:
                os.chdir(root)
                self.assertEqual(main(["init"]), 0)
                self.assertEqual(main(["map"]), 0)
                with GraphStore(root) as store:
                    counts = store.counts()
                self.assertGreaterEqual(counts["files"], 2)
                self.assertGreaterEqual(counts["symbols"], 2)
                self.assertGreaterEqual(counts["relations"], 2)
            finally:
                os.chdir(previous)

    def test_query_returns_symbol(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text("[project]\nname = 'sample'\n", encoding="utf-8")
            (root / "service.py").write_text("def calculate_total():\n    return 1\n", encoding="utf-8")
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                self.assertEqual(main(["query", "calculate"]), 0)
            finally:
                os.chdir(previous)

    def test_context_command_base_without_git(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["context", "fix login session bug"]), 0)
                rendered = output.getvalue()
                self.assertIn("Context pack for: fix login session bug", rendered)
                self.assertIn("src/auth/login.py", rendered)
                self.assertIn("Related symbols:", rendered)
            finally:
                os.chdir(previous)

    def test_context_json_output_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["context", "fix login session bug", "--json"]), 0)
                data = json.loads(output.getvalue())
                self.assertEqual(data["query"], "fix login session bug")
                self.assertIn("candidate_files", data)
                self.assertIn("suggested_first_reads", data)
                self.assertIn("related_symbols", data)
                self.assertIn("recent_commits", data)
            finally:
                os.chdir(previous)

    def test_context_scoring_prefers_path_symbol_and_commit_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                with GraphStore(root) as store:
                    store.replace_git_history(
                        [
                            {
                                "hash": "abc123456789",
                                "author": "Test",
                                "date": "2026-01-01T00:00:00+00:00",
                                "message": "fix login session bug",
                                "files": ["src/auth/login.py", "src/auth/session.py"],
                            }
                        ]
                )
                pack = build_context_pack(root, "fix login session bug")
                self.assertLessEqual(len(pack["candidate_files"]), 10)
                self.assertLessEqual(len(pack["related_symbols"]), 10)
                self.assertLessEqual(len(pack["recent_commits"]), 5)
                by_path = {item["path"]: item for item in pack["candidate_files"]}
                self.assertIn("src/auth/login.py", by_path)
                self.assertIn("src/auth/session.py", by_path)
                login = by_path["src/auth/login.py"]
                self.assertIn('path matches "login"', login["reasons"])
                self.assertIn('symbol matches "login"', login["reasons"])
                self.assertIn('commit message matches "fix"', login["reasons"])
            finally:
                os.chdir(previous)

    def test_context_deprioritizes_tests_for_non_test_query(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_scoring_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                pack = build_context_pack(root, "context scoring symbols")
                paths = [item["path"] for item in pack["candidate_files"]]
                self.assertIn("init_agent/context_builder.py", paths)
                self.assertIn("tests/test_base.py", paths)
                self.assertLess(paths.index("init_agent/context_builder.py"), paths.index("tests/test_base.py"))
                test_item = next(item for item in pack["candidate_files"] if item["path"] == "tests/test_base.py")
                self.assertIn("test file deprioritized for non-test query", test_item["reasons"])
            finally:
                os.chdir(previous)

    def test_context_keeps_tests_for_test_aware_query(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_scoring_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                pack = build_context_pack(root, "test context scoring")
                self.assertEqual(pack["candidate_files"][0]["path"], "tests/test_base.py")
                self.assertIn("test-aware query", pack["candidate_files"][0]["reasons"])
            finally:
                os.chdir(previous)

    def test_context_php_login_path_beats_common_admin_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_php_login_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                _add_admin_commit_noise(root)
                pack = build_context_pack(root, "login sessione admin")
                paths = [item["path"] for item in pack["candidate_files"]]
                self.assertIn("include/login.php", paths)
                self.assertIn("include/crm.php", paths)
                self.assertIn("include/core/organization.php", paths)
                self.assertIn("css/login.css", paths)
                self.assertIn("install/migrations/2026-06-16-admin-role-permissions.sql", paths)
                self.assertLess(paths.index("include/login.php"), paths.index("include/crm.php"))
                self.assertLess(paths.index("include/login.php"), paths.index("include/core/organization.php"))
                self.assertLess(paths.index("include/login.php"), paths.index("css/login.css"))
                self.assertLess(paths.index("include/login.php"), paths.index("install/migrations/2026-06-16-admin-role-permissions.sql"))
            finally:
                os.chdir(previous)

    def test_context_css_login_does_not_penalize_css(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_php_login_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                pack = build_context_pack(root, "css login")
                paths = [item["path"] for item in pack["candidate_files"][:3]]
                self.assertIn("css/login.css", paths)
                css_file = next(item for item in pack["candidate_files"] if item["path"] == "css/login.css")
                self.assertNotIn("asset file deprioritized for non-UI query", css_file["reasons"])
            finally:
                os.chdir(previous)

    def test_context_migration_intent_does_not_penalize_sql(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_php_login_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                pack = build_context_pack(root, "migration admin permissions")
                migration = next(
                    item
                    for item in pack["candidate_files"]
                    if item["path"] == "install/migrations/2026-06-16-admin-role-permissions.sql"
                )
                self.assertNotIn("migration file deprioritized for non-database query", migration["reasons"])
            finally:
                os.chdir(previous)

    def test_context_common_token_does_not_dominate_rare_token(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_php_login_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                _add_admin_commit_noise(root)
                pack = build_context_pack(root, "login sessione admin")
                login = next(item for item in pack["candidate_files"] if item["path"] == "include/login.php")
                crm = next(item for item in pack["candidate_files"] if item["path"] == "include/crm.php")
                self.assertGreater(login["score"], crm["score"])
                self.assertTrue(any('specific token "login" boosted' == reason for reason in login["reasons"]))
                self.assertTrue(any('common token "admin" downweighted' == reason for reason in crm["reasons"]))
            finally:
                os.chdir(previous)

    def test_context_relation_boost_does_not_beat_direct_path_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_php_login_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                pack = build_context_pack(root, "login admin")
                paths = [item["path"] for item in pack["candidate_files"]]
                self.assertLess(paths.index("include/login.php"), paths.index("include/crmFunction.php"))
                crm_function = next(item for item in pack["candidate_files"] if item["path"] == "include/crmFunction.php")
                related_reasons = [reason for reason in crm_function["reasons"] if reason.startswith("related to ")]
                self.assertLessEqual(len(related_reasons), 5)
            finally:
                os.chdir(previous)

    def test_context_php_login_json_output_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_php_login_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["context", "login sessione admin", "--json"]), 0)
                data = json.loads(output.getvalue())
                self.assertEqual(data["query"], "login sessione admin")
                self.assertEqual(data["candidate_files"][0]["path"], "include/login.php")
            finally:
                os.chdir(previous)

    def test_context_soft_path_match_finds_installazione(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "composer.json").write_text('{"name": "sample/app"}\n', encoding="utf-8")
            install = root / "install"
            include = root / "include"
            install.mkdir()
            include.mkdir()
            (install / "index.php").write_text("<?php\nfunction runInstaller() { return true; }\n", encoding="utf-8")
            (install / "README.md").write_text("# Install\nOpen /install/ in the browser.\n", encoding="utf-8")
            (include / "crm.php").write_text("<?php\nfunction crmHome() { return true; }\n", encoding="utf-8")
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                pack = build_context_pack(root, "procedura installazione")
                paths = [item["path"] for item in pack["candidate_files"]]
                self.assertIn("install/index.php", paths)
                self.assertLess(paths.index("install/index.php"), paths.index("include/crm.php") if "include/crm.php" in paths else 99)
                install_item = next(item for item in pack["candidate_files"] if item["path"] == "install/index.php")
                self.assertIn('path softly matches "installazione"', install_item["reasons"])
            finally:
                os.chdir(previous)

    def test_context_natural_italian_installation_query_prefers_install_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "composer.json").write_text('{"name": "sample/app"}\n', encoding="utf-8")
            (root / "install").mkdir()
            (root / "include").mkdir()
            (root / "js").mkdir()
            (root / "install" / "index.php").write_text(
                "<?php\nfunction runInstaller() { return true; }\n",
                encoding="utf-8",
            )
            (root / "install" / "schema.sql").write_text("CREATE TABLE settings (id INT);\n", encoding="utf-8")
            (root / "install" / "README.md").write_text("# Install\nOpen /install/ in the browser.\n", encoding="utf-8")
            (root / "include" / "session.php").write_text("<?php\nfunction sessionState() { return true; }\n", encoding="utf-8")
            (root / "include" / "core_modules.php").write_text(
                "<?php\nfunction fileRegistry() { return true; }\nfunction fileMetadata() { return true; }\n",
                encoding="utf-8",
            )
            (root / "js" / "flexcore.footer.js").write_text("function footerReady() { return true; }\n", encoding="utf-8")
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                pack = build_context_pack(
                    root,
                    "usando la skill riesci a capire se questa repository ha un file di installazione?",
                )
                paths = [item["path"] for item in pack["candidate_files"]]
                self.assertEqual(paths[0], "install/index.php")
                if "include/core_modules.php" in paths:
                    self.assertLess(paths.index("install/index.php"), paths.index("include/core_modules.php"))
                if "js/flexcore.footer.js" in paths:
                    self.assertLess(paths.index("install/index.php"), paths.index("js/flexcore.footer.js"))
                self.assertIn("install/README.md", paths[:5])
            finally:
                os.chdir(previous)

    def test_doctor_without_agent_is_not_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text("[project]\nname = 'sample'\n", encoding="utf-8")
            previous = Path.cwd()
            try:
                os.chdir(root)
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["doctor"]), 0)
                self.assertIn("NOT_READY", output.getvalue())
                self.assertFalse((root / ".agent").exists())
                report = run_doctor(root)
                self.assertEqual(report["status"], "NOT_READY")
                self.assertIn("init-agent init", report["suggested_commands"])
            finally:
                os.chdir(previous)

    def test_doctor_after_init_before_map_is_not_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text("[project]\nname = 'sample'\n", encoding="utf-8")
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                report = run_doctor(root)
                self.assertEqual(report["status"], "NOT_READY")
                self.assertEqual(report["stats"]["files"], 0)
                self.assertIn("init-agent map", report["suggested_commands"])
            finally:
                os.chdir(previous)

    def test_doctor_json_output_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text("[project]\nname = 'sample'\n", encoding="utf-8")
            (root / "app.py").write_text("def main():\n    return 1\n", encoding="utf-8")
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["doctor", "--json"]), 0)
                data = json.loads(output.getvalue())
                self.assertIn(data["status"], {"READY", "READY_WITH_WARNINGS", "NOT_READY"})
                self.assertIn("checks", data)
                self.assertIn("stats", data)
                self.assertIn("warnings", data)
                self.assertIn("suggested_commands", data)
            finally:
                os.chdir(previous)

    def test_doctor_final_status_ready_after_map_without_git(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text("[project]\nname = 'sample'\n", encoding="utf-8")
            (root / "app.py").write_text("def main():\n    return 1\n", encoding="utf-8")
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                report = run_doctor(root)
                self.assertEqual(report["status"], "READY")
                self.assertEqual(report["warnings"], [])
            finally:
                os.chdir(previous)

    def test_doctor_no_crash_outside_git_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text("[project]\nname = 'sample'\n", encoding="utf-8")
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["doctor"]), 0)
                self.assertIn("Git repository: NO", output.getvalue())
            finally:
                os.chdir(previous)

    def test_refresh_without_agent_or_database(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text("[project]\nname = 'sample'\n", encoding="utf-8")
            previous = Path.cwd()
            try:
                os.chdir(root)
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["refresh"]), 1)
                self.assertIn("init-agent init", output.getvalue())
                report = refresh_index(root)
                self.assertEqual(report["status"], "ERROR")
                self.assertIn("init-agent init", report["suggested_commands"])
            finally:
                os.chdir(previous)

    def test_refresh_after_map_without_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                report = refresh_index(root)
                self.assertEqual(report["status"], "OK")
                self.assertEqual(report["scanned_files"], 4)
                self.assertEqual(report["unchanged"], 4)
                self.assertEqual(report["added"], [])
                self.assertEqual(report["updated"], [])
                self.assertEqual(report["removed"], [])
            finally:
                os.chdir(previous)

    def test_refresh_detects_added_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                (root / "src" / "auth" / "token.py").write_text("def issueToken():\n    return 'x'\n", encoding="utf-8")
                report = refresh_index(root)
                self.assertEqual(report["status"], "OK")
                self.assertIn("src/auth/token.py", report["added"])
                with GraphStore(root) as store:
                    row = store.connection.execute("SELECT id FROM files WHERE path = ?", ("src/auth/token.py",)).fetchone()
                self.assertIsNotNone(row)
            finally:
                os.chdir(previous)

    def test_refresh_detects_modified_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                target = root / "src" / "auth" / "login.py"
                target.write_text("def loginUser():\n    return 'changed'\n\ndef logoutUser():\n    return True\n", encoding="utf-8")
                report = refresh_index(root)
                self.assertEqual(report["status"], "OK")
                self.assertIn("src/auth/login.py", report["updated"])
                with GraphStore(root) as store:
                    names = [
                        row["name"]
                        for row in store.connection.execute(
                            """
                            SELECT s.name
                            FROM symbols s
                            JOIN files f ON f.id = s.file_id
                            WHERE f.path = ?
                            """,
                            ("src/auth/login.py",),
                        )
                    ]
                self.assertIn("logoutUser", names)
            finally:
                os.chdir(previous)

    def test_refresh_detects_removed_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                (root / "src" / "auth" / "session.py").unlink()
                report = refresh_index(root)
                self.assertEqual(report["status"], "OK")
                self.assertIn("src/auth/session.py", report["removed"])
                with GraphStore(root) as store:
                    row = store.connection.execute("SELECT id FROM files WHERE path = ?", ("src/auth/session.py",)).fetchone()
                self.assertIsNone(row)
            finally:
                os.chdir(previous)

    def test_refresh_json_output_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["refresh", "--json"]), 0)
                data = json.loads(output.getvalue())
                self.assertEqual(data["status"], "OK")
                self.assertIn("scanned_files", data)
                self.assertIn("unchanged", data)
                self.assertIn("added", data)
                self.assertIn("updated", data)
                self.assertIn("removed", data)
                self.assertIn("errors", data)
            finally:
                os.chdir(previous)

    def test_refresh_no_crash_without_git(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text("[project]\nname = 'sample'\n", encoding="utf-8")
            (root / "app.py").write_text("def main():\n    return 1\n", encoding="utf-8")
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["refresh"]), 0)
                self.assertIn("Final result:\nOK", output.getvalue())
            finally:
                os.chdir(previous)

    def test_ignore_excludes_agents_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_ignore_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                paths = _indexed_paths(root)
                self.assertNotIn(".agents/skills/impeccable/scripts/tool.py", paths)
                self.assertIn("app.php", paths)
            finally:
                os.chdir(previous)

    def test_ignore_excludes_ds_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_ignore_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                self.assertNotIn("install/migrations/.DS_Store", _indexed_paths(root))
            finally:
                os.chdir(previous)

    def test_ignore_excludes_binary_extensions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_ignore_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                paths = _indexed_paths(root)
                self.assertNotIn("public/logo.png", paths)
                self.assertNotIn("docs/manual.pdf", paths)
                self.assertNotIn("data/cache.sqlite", paths)
            finally:
                os.chdir(previous)

    def test_ignore_custom_exclude_dirs_from_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_ignore_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                config = root / ".agent" / "config.json"
                data = json.loads(config.read_text(encoding="utf-8"))
                data["exclude_dirs"] = ["private"]
                config.write_text(json.dumps(data), encoding="utf-8")
                main(["map"])
                self.assertNotIn("private/secret.php", _indexed_paths(root))
            finally:
                os.chdir(previous)

    def test_doctor_ignores_excluded_unindexed_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_ignore_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                report = run_doctor(root)
                self.assertEqual(report["status"], "READY")
                self.assertFalse(any("project files are not indexed" in warning for warning in report["warnings"]))
            finally:
                os.chdir(previous)

    def test_refresh_does_not_index_excluded_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "composer.json").write_text('{"name": "sample/app"}\n', encoding="utf-8")
            (root / "app.php").write_text("<?php\nfunction appMain() { return true; }\n", encoding="utf-8")
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                agents = root / ".agents" / "skills"
                agents.mkdir(parents=True)
                (agents / "new_tool.py").write_text("def ignored():\n    return True\n", encoding="utf-8")
                (root / ".DS_Store").write_text("ignored", encoding="utf-8")
                (root / "graph.sqlite").write_text("ignored", encoding="utf-8")
                report = refresh_index(root)
                self.assertEqual(report["status"], "OK")
                self.assertNotIn(".agents/skills/new_tool.py", report["added"])
                self.assertNotIn(".DS_Store", report["added"])
                self.assertNotIn("graph.sqlite", report["added"])
                paths = _indexed_paths(root)
                self.assertNotIn(".agents/skills/new_tool.py", paths)
                self.assertNotIn(".DS_Store", paths)
                self.assertNotIn("graph.sqlite", paths)
            finally:
                os.chdir(previous)

    def test_context_json_stays_valid_with_ignore_rules(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_ignore_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["context", "app", "--json"]), 0)
                data = json.loads(output.getvalue())
                self.assertEqual(data["query"], "app")
                self.assertIn("candidate_files", data)
            finally:
                os.chdir(previous)

    def test_run_on_uninitialized_project_creates_agent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "composer.json").write_text('{"name": "sample/app"}\n', encoding="utf-8")
            (root / "include").mkdir()
            (root / "include" / "login.php").write_text("<?php\nfunction loginUser() { return true; }\n", encoding="utf-8")
            previous = Path.cwd()
            try:
                os.chdir(root)
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["run", "login"]), 0)
                self.assertTrue((root / ".agent").is_dir())
                self.assertTrue((root / ".agent" / "graph.sqlite").is_file())
                self.assertIn("Context pack for: login", output.getvalue())
            finally:
                os.chdir(previous)

    def test_run_on_mapped_project_uses_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["run", "login"]), 0)
                rendered = output.getvalue()
                self.assertIn("- Map: skipped", rendered)
                self.assertIn("- Refresh: OK", rendered)
            finally:
                os.chdir(previous)

    def test_run_without_git_does_not_crash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["run", "login"]), 0)
                self.assertIn("- Git: not available", output.getvalue())
            finally:
                os.chdir(previous)

    def test_run_json_output_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["run", "login", "--json"]), 0)
                data = json.loads(output.getvalue())
                self.assertEqual(data["query"], "login")
                self.assertIn("preparation", data)
                self.assertIn("context", data)
                self.assertIn("candidate_files", data["context"])
            finally:
                os.chdir(previous)

    def test_run_markdown_output_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["run", "login", "--markdown"]), 0)
                rendered = output.getvalue()
                self.assertIn("# Init Agent Context Pack", rendered)
                self.assertIn("## Preparation", rendered)
                self.assertIn("## Suggested first reads", rendered)
            finally:
                os.chdir(previous)

    def test_run_generates_final_context_pack(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["run", "login session"]), 0)
                rendered = output.getvalue()
                self.assertIn("src/auth/login.py", rendered)
                self.assertIn("Suggested first reads:", rendered)
            finally:
                os.chdir(previous)

    def test_recent_commit_files_are_truncated_in_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_many_commit_files_fixture(Path(tmp), total_files=15)
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                _add_big_commit(root, total_files=15)
                pack = build_context_pack(root, "admin login")
                commit = pack["recent_commits"][0]
                self.assertEqual(len(commit["files"]), 10)
                self.assertEqual(commit["total_files"], 15)
                self.assertTrue(commit["files_truncated"])
            finally:
                os.chdir(previous)

    def test_recent_commit_files_not_truncated_when_small(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_many_commit_files_fixture(Path(tmp), total_files=4)
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                _add_big_commit(root, total_files=4)
                pack = build_context_pack(root, "admin login")
                commit = pack["recent_commits"][0]
                self.assertEqual(len(commit["files"]), 4)
                self.assertEqual(commit["total_files"], 4)
                self.assertFalse(commit["files_truncated"])
            finally:
                os.chdir(previous)

    def test_run_markdown_does_not_print_large_commit_file_lists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_many_commit_files_fixture(Path(tmp), total_files=15)
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                _add_big_commit(root, total_files=15)
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["run", "admin login", "--markdown"]), 0)
                rendered = output.getvalue()
                self.assertIn("files: 10 of 15 shown", rendered)
                recent_commits = rendered.split("## Recent related commits", 1)[1]
                self.assertNotIn("file_14.php", recent_commits)
            finally:
                os.chdir(previous)

    def test_run_json_with_truncated_commits_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_many_commit_files_fixture(Path(tmp), total_files=15)
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                _add_big_commit(root, total_files=15)
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["run", "admin login", "--json"]), 0)
                data = json.loads(output.getvalue())
                commit = data["context"]["recent_commits"][0]
                self.assertEqual(commit["total_files"], 15)
                self.assertTrue(commit["files_truncated"])
                self.assertEqual(len(commit["files"]), 10)
            finally:
                os.chdir(previous)

    def test_estimate_produces_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["estimate", "login"]), 0)
                rendered = output.getvalue()
                self.assertIn("Init Agent Token Estimate", rendered)
                self.assertIn("Estimated savings:", rendered)
            finally:
                os.chdir(previous)

    def test_estimate_json_output_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["estimate", "login", "--json"]), 0)
                data = json.loads(output.getvalue())
                self.assertEqual(data["query"], "login")
                self.assertIn("context_pack", data)
                self.assertIn("suggested_first_reads", data)
                self.assertIn("top_candidates", data)
                self.assertIn("indexed_project", data)
                self.assertIn("estimated_savings", data)
            finally:
                os.chdir(previous)

    def test_estimate_tokens_uses_ceil_chars_over_four(self) -> None:
        self.assertEqual(estimate_tokens(0), 0)
        self.assertEqual(estimate_tokens(1), 1)
        self.assertEqual(estimate_tokens(4), 1)
        self.assertEqual(estimate_tokens(5), 2)

    def test_estimate_does_not_crash_with_missing_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                (root / "src" / "auth" / "login.py").unlink()
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["estimate", "login", "--json"]), 0)
                data = json.loads(output.getvalue())
                self.assertGreaterEqual(data["indexed_project"]["characters"], 0)
            finally:
                os.chdir(previous)

    def test_estimate_respects_excluded_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_ignore_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["estimate", "app", "--json"]), 0)
                data = json.loads(output.getvalue())
                self.assertLess(data["indexed_project"]["files_count"], 5)
                self.assertNotIn("public/logo.png", data["suggested_first_reads"]["files"])
            finally:
                os.chdir(previous)


def _create_context_fixture(root: Path) -> Path:
    (root / "pyproject.toml").write_text("[project]\nname = 'sample'\n", encoding="utf-8")
    auth_dir = root / "src" / "auth"
    auth_dir.mkdir(parents=True)
    (auth_dir / "login.py").write_text(
        "from src.auth.session import validateSession\n\n"
        "def loginUser():\n"
        "    return validateSession()\n",
        encoding="utf-8",
    )
    (auth_dir / "session.py").write_text(
        "SESSION_TIMEOUT = 300\n\n"
        "def validateSession():\n"
        "    return True\n",
        encoding="utf-8",
    )
    (root / "README.md").write_text("# Sample\n", encoding="utf-8")
    return root


def _create_context_scoring_fixture(root: Path) -> Path:
    (root / "pyproject.toml").write_text("[project]\nname = 'sample'\n", encoding="utf-8")
    source_dir = root / "init_agent"
    test_dir = root / "tests"
    source_dir.mkdir()
    test_dir.mkdir()
    (source_dir / "context_builder.py").write_text(
        "def build_context_pack():\n"
        "    return []\n\n"
        "def score_context_symbols():\n"
        "    return 1\n",
        encoding="utf-8",
    )
    (test_dir / "test_base.py").write_text(
        "def test_context_scoring_symbols():\n"
        "    assert True\n\n"
        "def test_context_scoring_behavior():\n"
        "    assert True\n",
        encoding="utf-8",
    )
    return root


def _create_php_login_fixture(root: Path) -> Path:
    (root / "composer.json").write_text('{"name": "sample/app"}\n', encoding="utf-8")
    include = root / "include"
    core = include / "core"
    gst = include / "gst"
    css = root / "css"
    migrations = root / "install" / "migrations"
    core.mkdir(parents=True)
    gst.mkdir(parents=True)
    css.mkdir()
    migrations.mkdir(parents=True)
    (include / "login.php").write_text(
        "<?php\n"
        "function loginUtente($admin) { return validaSessione($admin); }\n"
        "function validaSessione($admin) { return true; }\n",
        encoding="utf-8",
    )
    (include / "crm.php").write_text(
        "<?php\n"
        "require_once 'login.php';\n"
        "function adminDashboard() { return true; }\n"
        "function adminCustomerList() { return true; }\n"
        "function adminCrmPanel() { return true; }\n",
        encoding="utf-8",
    )
    (include / "crmFunction.php").write_text(
        "<?php\n"
        "require_once 'login.php';\n"
        "function adminHelper() { return true; }\n"
        "function adminPermission() { return true; }\n"
        "function adminReport() { return true; }\n",
        encoding="utf-8",
    )
    (core / "organization.php").write_text(
        "<?php\n"
        "require_once '../login.php';\n"
        "function adminOrganization() { return true; }\n"
        "function adminUnit() { return true; }\n",
        encoding="utf-8",
    )
    (gst / "generate_config.php").write_text(
        "<?php\n"
        "function adminGenerateConfig() { return true; }\n",
        encoding="utf-8",
    )
    (css / "login.css").write_text(
        ".login-admin-panel { color: #111; }\n"
        ".session-warning { display: block; }\n",
        encoding="utf-8",
    )
    (migrations / "2026-06-16-admin-role-permissions.sql").write_text(
        "CREATE TABLE admin_role_permissions (id integer primary key, permission text);\n"
        "INSERT INTO admin_role_permissions(permission) VALUES ('login_sessione_admin');\n",
        encoding="utf-8",
    )
    return root


def _add_admin_commit_noise(root: Path) -> None:
    with GraphStore(root) as store:
        store.replace_git_history(
            [
                {
                    "hash": f"abc12345{index}",
                    "author": "Test",
                    "date": f"2026-01-0{index + 1}T00:00:00+00:00",
                    "message": f"admin crm organization update {index}",
                    "files": ["include/crm.php", "include/crmFunction.php", "include/core/organization.php"],
                }
                for index in range(5)
            ]
        )


def _create_many_commit_files_fixture(root: Path, total_files: int) -> Path:
    (root / "composer.json").write_text('{"name": "sample/app"}\n', encoding="utf-8")
    include = root / "include"
    include.mkdir()
    for index in range(total_files):
        name = "login.php" if index == 0 else f"file_{index}.php"
        symbol = "loginAdmin" if index == 0 else f"adminFile{index}"
        (include / name).write_text(f"<?php\nfunction {symbol}() {{ return true; }}\n", encoding="utf-8")
    return root


def _add_big_commit(root: Path, total_files: int) -> None:
    files = ["include/login.php"] + [f"include/file_{index}.php" for index in range(1, total_files)]
    with GraphStore(root) as store:
        store.replace_git_history(
            [
                {
                    "hash": "abc123bigcommit",
                    "author": "Test",
                    "date": "2026-01-01T00:00:00+00:00",
                    "message": "admin login update",
                    "files": files,
                }
            ]
        )


def _create_ignore_fixture(root: Path) -> Path:
    (root / "composer.json").write_text('{"name": "sample/app"}\n', encoding="utf-8")
    (root / "app.php").write_text("<?php\nfunction appMain() { return true; }\n", encoding="utf-8")
    agents = root / ".agents" / "skills" / "impeccable" / "scripts"
    agents.mkdir(parents=True)
    (agents / "tool.py").write_text("def ignored():\n    return True\n", encoding="utf-8")
    migrations = root / "install" / "migrations"
    migrations.mkdir(parents=True)
    (migrations / ".DS_Store").write_text("ignored", encoding="utf-8")
    public = root / "public"
    docs = root / "docs"
    data = root / "data"
    private = root / "private"
    public.mkdir()
    docs.mkdir()
    data.mkdir()
    private.mkdir()
    (public / "logo.png").write_bytes(b"png")
    (docs / "manual.pdf").write_bytes(b"pdf")
    (data / "cache.sqlite").write_bytes(b"sqlite")
    (private / "secret.php").write_text("<?php\nfunction privateSecret() { return true; }\n", encoding="utf-8")
    return root


def _indexed_paths(root: Path) -> set[str]:
    with GraphStore(root) as store:
        return {row["path"] for row in store.connection.execute("SELECT path FROM files").fetchall()}


if __name__ == "__main__":
    unittest.main()
