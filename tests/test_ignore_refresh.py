from tests.support import *


class IgnoreRefreshTests(InitAgentTestCase):
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

    def test_doctor_warns_when_index_version_is_stale(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_php_call_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                _mark_index_stale(root)
                report = run_doctor(root)
                self.assertEqual(report["status"], "READY_WITH_WARNINGS")
                self.assertIn("init-agent map", report["suggested_commands"])
                self.assertTrue(any("older extractor" in warning for warning in report["warnings"]))
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

    def test_refresh_reports_stale_index_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_php_call_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                _mark_index_stale(root)
                report = refresh_index(root)
                self.assertEqual(report["status"], "ERROR")
                self.assertIn("init-agent map", report["suggested_commands"])
                self.assertTrue(any("older extractor" in error for error in report["errors"]))
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

    def test_ignore_excludes_github_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_ignore_fixture(Path(tmp))
            (root / ".github" / "workflows").mkdir(parents=True)
            (root / ".github" / "workflows" / "ci.yml").write_text("name: CI\n", encoding="utf-8")
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                self.assertNotIn(".github/workflows/ci.yml", _indexed_paths(root))
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
                self.assertNotIn("public/icon.svg", paths)
                self.assertNotIn("public/logo.ai", paths)
                self.assertNotIn("docs/manual.pdf", paths)
                self.assertNotIn("data/cache.sqlite", paths)
            finally:
                os.chdir(previous)

    def test_ignore_excludes_python_package_metadata_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_ignore_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                paths = _indexed_paths(root)
                self.assertNotIn("sample.egg-info/PKG-INFO", paths)
                self.assertNotIn("sample-1.0.dist-info/METADATA", paths)
            finally:
                os.chdir(previous)

    def test_ignore_excludes_common_env_and_cache_dirs_without_gitignore(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_ignore_fixture(Path(tmp))
            (root / ".venv" / "lib").mkdir(parents=True)
            (root / ".venv" / "lib" / "site.py").write_text("def ignored():\n    return True\n", encoding="utf-8")
            (root / "venv" / "lib").mkdir(parents=True)
            (root / "venv" / "lib" / "site.py").write_text("def ignored2():\n    return True\n", encoding="utf-8")
            (root / ".pytest_cache").mkdir()
            (root / ".pytest_cache" / "cache.py").write_text("def ignored3():\n    return True\n", encoding="utf-8")
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                paths = _indexed_paths(root)
                self.assertNotIn(".venv/lib/site.py", paths)
                self.assertNotIn("venv/lib/site.py", paths)
                self.assertNotIn(".pytest_cache/cache.py", paths)
                self.assertIn("app.php", paths)
            finally:
                os.chdir(previous)

    def test_git_indexing_respects_gitignore_and_internal_excludes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text("[project]\nname = 'sample'\n", encoding="utf-8")
            (root / "app.py").write_text("def app_main():\n    return True\n", encoding="utf-8")
            (root / ".gitignore").write_text("ignored_dir/\n", encoding="utf-8")
            (root / "ignored_dir").mkdir()
            (root / "ignored_dir" / "ignored.py").write_text("def ignored():\n    return True\n", encoding="utf-8")
            (root / ".venv" / "lib").mkdir(parents=True)
            (root / ".venv" / "lib" / "site.py").write_text("def ignored_env():\n    return True\n", encoding="utf-8")
            subprocess.run(["git", "init"], cwd=root, text=True, capture_output=True, check=True)
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                paths = _indexed_paths(root)
                self.assertIn("app.py", paths)
                self.assertNotIn("ignored_dir/ignored.py", paths)
                self.assertNotIn(".venv/lib/site.py", paths)
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
                data["exclude_dirs"] = ["excluded"]
                config.write_text(json.dumps(data), encoding="utf-8")
                main(["map"])
                self.assertNotIn("excluded/local_only.php", _indexed_paths(root))
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
                egg_info = root / "sample.egg-info"
                egg_info.mkdir()
                (egg_info / "PKG-INFO").write_text("ignored", encoding="utf-8")
                report = refresh_index(root)
                self.assertEqual(report["status"], "OK")
                self.assertNotIn(".agents/skills/new_tool.py", report["added"])
                self.assertNotIn(".DS_Store", report["added"])
                self.assertNotIn("graph.sqlite", report["added"])
                self.assertNotIn("sample.egg-info/PKG-INFO", report["added"])
                paths = _indexed_paths(root)
                self.assertNotIn(".agents/skills/new_tool.py", paths)
                self.assertNotIn(".DS_Store", paths)
                self.assertNotIn("graph.sqlite", paths)
                self.assertNotIn("sample.egg-info/PKG-INFO", paths)
            finally:
                os.chdir(previous)
