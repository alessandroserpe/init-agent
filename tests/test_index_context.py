from tests.support import *


class IndexContextTests(InitAgentTestCase):
    def test_cli_init_and_map(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text("[project]\nname = 'sample'\n", encoding="utf-8")
            (root / "app.py").write_text("class MCPServerStartup:\n    pass\n\ndef main():\n    return MCPServerStartup()\n", encoding="utf-8")
            previous = Path.cwd()
            try:
                os.chdir(root)
                self.assertEqual(main(["init"]), 0)
                self.assertEqual(main(["map"]), 0)
                with GraphStore(root) as store:
                    counts = store.counts()
                    term_count = store.connection.execute("SELECT COUNT(*) AS count FROM term_stats").fetchone()["count"]
                    tags = {
                        row["tag"]
                        for row in store.connection.execute(
                            """
                            SELECT t.tag
                            FROM file_tags t
                            JOIN files f ON f.id = t.file_id
                            WHERE f.path = 'app.py'
                            """
                        ).fetchall()
                    }
                self.assertGreaterEqual(counts["files"], 2)
                self.assertGreaterEqual(counts["symbols"], 2)
                self.assertGreaterEqual(counts["relations"], 2)
                self.assertGreater(term_count, 0)
                self.assertIn("mcp", tags)
                self.assertIn("server", tags)
                self.assertIn("startup", tags)
            finally:
                os.chdir(previous)

    def test_map_indexes_documentation_and_config_symbols(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("# Demo\n\n## Quick Start\n\n```bash\ninit-agent run login\n```\n", encoding="utf-8")
            (root / "package.json").write_text('{"name": "demo", "scripts": {"test": "node test.js"}}\n', encoding="utf-8")
            (root / "pyproject.toml").write_text("[project]\nname = 'demo'\n[project.scripts]\ndemo = 'demo.cli:main'\n", encoding="utf-8")
            (root / "compose.yaml").write_text("services:\n  web: {}\n", encoding="utf-8")
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                with GraphStore(root) as store:
                    rows = {
                        (row["name"], row["kind"], row["path"])
                        for row in store.connection.execute(
                            """
                            SELECT s.name, s.kind, f.path
                            FROM symbols s
                            JOIN files f ON f.id = s.file_id
                            """
                        ).fetchall()
                    }
                self.assertIn(("Quick Start", "heading", "README.md"), rows)
                self.assertIn(("init-agent run login", "command_example", "README.md"), rows)
                self.assertIn(("test", "package_script", "package.json"), rows)
                self.assertIn(("demo", "project_script", "pyproject.toml"), rows)
                self.assertIn(("services", "config_key", "compose.yaml"), rows)
            finally:
                os.chdir(previous)

    def test_map_indexes_route_symbols_and_handler_relations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text('{"name": "sample"}\n', encoding="utf-8")
            (root / "server.js").write_text("function showUser(req, res) {}\napp.get('/users/:id', showUser)\n", encoding="utf-8")
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                with GraphStore(root) as store:
                    symbols = {
                        (row["name"], row["kind"])
                        for row in store.connection.execute("SELECT name, kind FROM symbols").fetchall()
                    }
                    relations = {
                        (row["relation"], row["target_type"], row["target_id"])
                        for row in store.connection.execute("SELECT relation, target_type, target_id FROM relations").fetchall()
                    }
                self.assertIn(("/users/:id", "route"), symbols)
                self.assertIn(("route_to_handler", "symbol_name", "showUser"), relations)
            finally:
                os.chdir(previous)

    def test_term_stats_downweight_common_repo_terms(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "composer.json").write_text('{"name": "sample/app"}\n', encoding="utf-8")
            include = root / "include"
            include.mkdir()
            (include / "login.php").write_text("<?php\nfunction loginUser() { return true; }\n", encoding="utf-8")
            for index in range(8):
                (include / f"admin_{index}.php").write_text(
                    f"<?php\nfunction adminHelper{index}() {{ return true; }}\n",
                    encoding="utf-8",
                )
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                with GraphStore(root) as store:
                    rows = {
                        row["term"]: row["weight"]
                        for row in store.connection.execute(
                            "SELECT term, weight FROM term_stats WHERE source = 'all' AND term IN ('admin', 'login')"
                        ).fetchall()
                    }
                self.assertLess(rows["admin"], rows["login"])
                pack = build_context_pack(root, "login admin")
                self.assertEqual(pack["candidate_files"][0]["path"], "include/login.php")
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

    def test_context_php_call_relation_finds_caller_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_php_call_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                pack = build_context_pack(root, "buildForm")
                paths = [item["path"] for item in pack["candidate_files"]]
                self.assertIn("index.php", paths)
                self.assertIn("include/functions.php", paths)
                index_item = next(item for item in pack["candidate_files"] if item["path"] == "index.php")
                self.assertIn('calls "buildForm"', index_item["reasons"])
            finally:
                os.chdir(previous)

    def test_related_php_call_relation_resolves_definition_and_callers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_php_call_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                index_related = related_query(root, "index.php")
                self.assertIsNotNone(index_related)
                raw_relation_names = {item["relation"] for item in index_related["relations"]}
                self.assertNotIn("calls", raw_relation_names)
                self.assertNotIn("defines", raw_relation_names)
                resolved = index_related["resolved_calls"]
                crea_form = next(item for item in resolved if item["name"] == "buildForm")
                self.assertEqual(crea_form["definitions"][0]["path"], "include/functions.php")

                functions_related = related_query(root, "include/functions.php")
                self.assertIsNotNone(functions_related)
                callers = {(item["path"], item["name"]) for item in functions_related["callers"]}
                self.assertIn(("index.php", "buildForm"), callers)
                index_caller = next(item for item in functions_related["callers"] if item["path"] == "index.php" and item["name"] == "buildForm")
                self.assertEqual(index_caller["call_count"], 1)
                self.assertEqual(index_caller["first_line"], 3)
            finally:
                os.chdir(previous)

    def test_callers_command_shows_php_callers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_php_call_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["callers", "buildForm"]), 0)
                rendered = output.getvalue()
                self.assertIn("Symbol: buildForm", rendered)
                self.assertIn("function include/functions.php:2", rendered)
                self.assertIn("index.php:3 calls buildForm (1x)", rendered)
            finally:
                os.chdir(previous)

    def test_symbol_command_shows_definitions_callers_and_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_php_call_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["symbol", "buildForm"]), 0)
                rendered = output.getvalue()
                self.assertIn("Symbol: buildForm", rendered)
                self.assertIn("Definitions:", rendered)
                self.assertIn("function include/functions.php:2", rendered)
                self.assertIn("Callers:", rendered)
                self.assertIn("index.php:3 calls buildForm (1x)", rendered)
                self.assertIn("Candidate files:", rendered)
                self.assertIn("include/functions.php", rendered)
                self.assertIn("Recent commits:", rendered)
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
            (root / "js" / "app.footer.js").write_text("function footerReady() { return true; }\n", encoding="utf-8")
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
                if "js/app.footer.js" in paths:
                    self.assertLess(paths.index("install/index.php"), paths.index("js/app.footer.js"))
                self.assertIn("install/README.md", paths[:5])
            finally:
                os.chdir(previous)

    def test_context_ignores_function_words_for_django_like_query(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text("[project]\nname = 'sample'\n", encoding="utf-8")
            for directory in [
                "django/contrib/admin/static/admin/js",
                "django/contrib/admin/templatetags",
                "django/core",
                "tests/validation",
                "django/contrib/auth/migrations",
            ]:
                (root / directory).mkdir(parents=True)
            (root / "django/contrib/admin/static/admin/js/change_form.js").write_text(
                "const form = document.querySelector('form');\nfunction displayMessages() { return form; }\n",
                encoding="utf-8",
            )
            (root / "django/contrib/admin/templatetags/admin_modify.py").write_text(
                "def render_change_form():\n    return 'form validation error messages'\n",
                encoding="utf-8",
            )
            (root / "django/core/exceptions.py").write_text(
                "class ValidationError(Exception):\n    pass\n\ndef not_are_after_noise():\n    return None\n",
                encoding="utf-8",
            )
            (root / "tests/validation/test_error_messages.py").write_text(
                "def test_validation_error_messages():\n    assert True\n",
                encoding="utf-8",
            )
            (root / "django/contrib/auth/migrations/0007_alter_validators_add_error_messages.py").write_text(
                "def alter_validators_add_error_messages():\n    return None\n",
                encoding="utf-8",
            )
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                pack = build_context_pack(root, "why are messages not displayed after form validation error in Django admin")
                paths = [item["path"] for item in pack["candidate_files"]]
                self.assertLess(
                    paths.index("django/contrib/admin/static/admin/js/change_form.js"),
                    paths.index("tests/validation/test_error_messages.py"),
                )
                if "django/contrib/auth/migrations/0007_alter_validators_add_error_messages.py" in paths:
                    self.assertLess(
                        paths.index("django/contrib/admin/static/admin/js/change_form.js"),
                        paths.index("django/contrib/auth/migrations/0007_alter_validators_add_error_messages.py"),
                    )
                rendered_reasons = "\n".join(reason for item in pack["candidate_files"] for reason in item["reasons"])
                self.assertNotIn('"are"', rendered_reasons)
                self.assertNotIn('"not"', rendered_reasons)
                self.assertNotIn('"after"', rendered_reasons)
                self.assertNotIn('"why"', rendered_reasons)
            finally:
                os.chdir(previous)

    def test_context_ignores_function_words_for_express_like_query(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text('{"name": "sample"}\n', encoding="utf-8")
            (root / "lib").mkdir()
            (root / "examples").mkdir()
            (root / "lib" / "application.js").write_text(
                "function dispatch(req, res) { return req; }\nfunction middleware(fn) { return fn; }\n",
                encoding="utf-8",
            )
            (root / "examples" / "route-middleware.js").write_text(
                "function andRestrictToSelf(req, res) { return true; }\n",
                encoding="utf-8",
            )
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                pack = build_context_pack(root, "where routes and middleware requests are dispatched")
                rendered_reasons = "\n".join(reason for item in pack["candidate_files"] for reason in item["reasons"])
                self.assertNotIn('"and"', rendered_reasons)
                self.assertNotIn('"where"', rendered_reasons)
                self.assertNotIn('"are"', rendered_reasons)
                self.assertIn("lib/application.js", [item["path"] for item in pack["candidate_files"]])
            finally:
                os.chdir(previous)

    def test_context_deprioritizes_examples_and_docs_for_operational_query(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text('{"name": "sample"}\n', encoding="utf-8")
            for directory in ("src/optimizer", "playground/optimizer", "docs/guide"):
                (root / directory).mkdir(parents=True)
            (root / "src/optimizer/cache.ts").write_text(
                "export function optimizeDepsCache() { return true; }\n",
                encoding="utf-8",
            )
            for name in ("index", "resolve", "scanner", "metadata", "server", "plugin", "runtime", "invalidation"):
                (root / "src" / "optimizer" / f"{name}.ts").write_text(
                    f"export function {name}OptimizerCacheInvalidation() {{ return true; }}\n",
                    encoding="utf-8",
                )
            (root / "playground/optimizer/cache-demo.ts").write_text(
                "export function optimizeDepsCacheDemo() { return true; }\n",
                encoding="utf-8",
            )
            (root / "docs/guide/dep-pre-bundling.md").write_text(
                "# Optimize deps cache\n\nDependency optimizer cache guide.\n",
                encoding="utf-8",
            )
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                pack = build_context_pack(root, "debug optimizer cache invalidation")
                paths = [item["path"] for item in pack["candidate_files"]]
                self.assertLess(paths.index("src/optimizer/cache.ts"), paths.index("playground/optimizer/cache-demo.ts"))
                self.assertNotIn("docs/guide/dep-pre-bundling.md", paths)
                playground = next(item for item in pack["candidate_files"] if item["path"] == "playground/optimizer/cache-demo.ts")
                self.assertIn("example/playground deprioritized for non-example query", playground["reasons"])
                docs_pack = build_context_pack(root, "docs optimizer cache guide")
                self.assertEqual(docs_pack["candidate_files"][0]["path"], "docs/guide/dep-pre-bundling.md")
            finally:
                os.chdir(previous)

    def test_context_matches_query_token_inside_compound_filename(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text("[project]\nname = 'tooling'\n", encoding="utf-8")
            source = root / "src" / "_pytest"
            source.mkdir(parents=True)
            (source / "fixtures.py").write_text(
                "def resolve_fixture():\n    return True\n",
                encoding="utf-8",
            )
            (source / "setupplan.py").write_text(
                "def pytest_fixture_setup():\n    return True\n",
                encoding="utf-8",
            )
            for name in ("capture", "debugging", "doctest", "hookspec", "logging", "python", "runner", "unittest"):
                (source / f"{name}.py").write_text(
                    "def setup():\n    return True\n",
                    encoding="utf-8",
                )
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                pack = build_context_pack(root, "pytest fixtures setup")
                paths = [item["path"] for item in pack["candidate_files"]]
                self.assertIn("src/_pytest/setupplan.py", paths[:5])
                setupplan = next(item for item in pack["candidate_files"] if item["path"] == "src/_pytest/setupplan.py")
                self.assertIn('filename contains "setup"', setupplan["reasons"])
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

    def test_context_pack_reports_low_confidence_for_broad_noisy_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text("[project]\nname = 'sample'\n", encoding="utf-8")
            source = root / "src"
            source.mkdir()
            for index in range(8):
                (source / f"manager_{index}.py").write_text(
                    f"def helper_{index}():\n    return {index}\n",
                    encoding="utf-8",
                )
            _prepare_index(root)
            pack = build_context_pack(root, "manager")
            self.assertIn(pack["confidence"]["level"], {"low", "medium"})
            self.assertTrue(pack["next_agent_actions"])
            commands = [item["command"] for item in pack["next_agent_actions"]]
            self.assertIn("init-agent doctor", commands)
            self.assertIn("init-agent map", commands)

    def test_context_pack_guides_symptom_queries_to_failing_test_related_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text("[project]\nname = 'sample'\n", encoding="utf-8")
            test_dir = root / "tests" / "template_tests"
            test_dir.mkdir(parents=True)
            (test_dir / "test_response.py").write_text(
                "class GeneratedContentPunctuationRegressionTest:\n"
                "    def test_sentence_terminal_marker_stays_outside_generated_anchor(self):\n"
                "        assert render_response('example.com!')\n",
                encoding="utf-8",
            )
            template_dir = root / "django" / "template"
            template_dir.mkdir(parents=True)
            (template_dir / "response.py").write_text("class TemplateResponse: pass\n", encoding="utf-8")
            (template_dir / "base.py").write_text("def render_response(value):\n    return value\n", encoding="utf-8")
            http_dir = root / "django" / "http"
            http_dir.mkdir(parents=True)
            (http_dir / "response.py").write_text("class HttpResponse: pass\n", encoding="utf-8")
            utils_dir = root / "django" / "utils"
            utils_dir.mkdir(parents=True)
            (utils_dir / "html.py").write_text("def normalize_terminal_marker(value):\n    return value\n", encoding="utf-8")

            _prepare_index(root)
            pack = build_context_pack(
                root,
                "template response regression GeneratedContentPunctuationRegressionTest terminal marker rendered output wrong",
            )

            self.assertIn(pack["confidence"]["level"], {"low", "medium"})
            self.assertIn(
                "symptom or failing-test query may point at high-level files before the underlying cause",
                pack["confidence"]["reasons"],
            )
            actions = pack["next_agent_actions"]
            self.assertEqual(actions[0]["action"], "inspect_failing_test_neighborhood")
            self.assertEqual(actions[0]["command"], "init-agent related tests/template_tests/test_response.py")

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

    def test_run_rebuilds_stale_index_and_accepts_unquoted_query_words(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_php_call_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                _mark_index_stale(root)
                with GraphStore(root) as store:
                    store.connection.execute("DELETE FROM relations WHERE relation = 'calls'")
                    store.connection.commit()
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["run", "dove", "viene", "chiamata", "buildForm", "--json"]), 0)
                data = json.loads(output.getvalue())
                self.assertEqual(data["query"], "dove viene chiamata buildForm")
                self.assertEqual(data["preparation"]["map"], "done")
                self.assertTrue(any("older extractor" in warning for warning in data["preparation"]["warnings"]))
                paths = [item["path"] for item in data["context"]["candidate_files"]]
                self.assertIn("index.php", paths)
                index_item = next(item for item in data["context"]["candidate_files"] if item["path"] == "index.php")
                self.assertIn('calls "buildForm"', index_item["reasons"])
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
                self.assertIn("## Useful follow-up commands", rendered)
                self.assertIn("## Safety notes", rendered)
                self.assertIn("init-agent related src/auth/login.py", rendered)
                self.assertIn('init-agent feedback add "login"', rendered)
                self.assertIn("Heuristic orientation only; verify files before editing.", rendered)
            finally:
                os.chdir(previous)

    def test_run_markdown_handoff_suggests_symbol_followups(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["run", "login session", "--markdown"]), 0)
                rendered = output.getvalue()
                self.assertIn("## Useful follow-up commands", rendered)
                self.assertIn("init-agent callers loginUser", rendered)
                self.assertIn("init-agent related src/auth/login.py", rendered)
                self.assertIn("Feedback should be recorded only after files are verified.", rendered)
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

    def test_overview_prefers_manifest_entry_points_and_subsystems(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_overview_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["overview"]), 0)
                rendered = output.getvalue()
                self.assertIn("Init Agent Repository Overview", rendered)
                self.assertIn("pyproject.toml", rendered)
                self.assertIn("src/sample/cli.py", rendered)
                self.assertIn("src/sample/server.py", rendered)
                self.assertIn("frontend/package.json", rendered)
                self.assertIn("Major subsystems:", rendered)
            finally:
                os.chdir(previous)

    def test_overview_json_output_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_overview_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["overview", "--json"]), 0)
                data = json.loads(output.getvalue())
                self.assertIn("project", data)
                self.assertIn("suggested_first_reads", data)
                self.assertIn("entry_points", data)
                self.assertIn("manifests", data)
                self.assertIn("subsystems", data)
                paths = [item["path"] for item in data["suggested_first_reads"]]
                self.assertIn("pyproject.toml", paths)
                self.assertLess(paths.index("pyproject.toml"), paths.index("tests/test_cli.py") if "tests/test_cli.py" in paths else 99)
            finally:
                os.chdir(previous)

    def test_run_overview_prepares_uninitialized_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_overview_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["run", "--overview", "--json"]), 0)
                data = json.loads(output.getvalue())
                self.assertEqual(data["preparation"]["init"], "done")
                self.assertEqual(data["preparation"]["map"], "done")
                self.assertTrue((root / ".agent" / "graph.sqlite").exists())
                self.assertIn("overview", data)
                self.assertIn("pyproject.toml", [item["path"] for item in data["overview"]["manifests"]])
            finally:
                os.chdir(previous)

    def test_run_overview_markdown_is_compact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_overview_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["run", "--overview", "--markdown"]), 0)
                rendered = output.getvalue()
                self.assertIn("# Init Agent Repository Overview", rendered)
                self.assertIn("## Suggested first reads", rendered)
                self.assertIn("## Likely entry points", rendered)
                self.assertIn("Heuristic overview", rendered)
            finally:
                os.chdir(previous)

    def test_overview_caps_repeated_test_routes_and_prefers_core_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "composer.json").write_text('{"name": "sample/framework"}\n', encoding="utf-8")
            (root / "README.md").write_text("# Sample Framework\n", encoding="utf-8")
            source = root / "src" / "Framework" / "Foundation"
            tests = root / "tests" / "Integration" / "Routing"
            source.mkdir(parents=True)
            tests.mkdir(parents=True)
            (source / "Application.php").write_text(
                "<?php\nclass Application { public function boot() { return true; } }\n",
                encoding="utf-8",
            )
            noisy_routes = "\n".join(f"Route::get('/fixture-{index}', Handler::class);" for index in range(40))
            (tests / "RouteFixtureTest.php").write_text(f"<?php\n{noisy_routes}\n", encoding="utf-8")
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["overview", "--json"]), 0)
                data = json.loads(output.getvalue())
                paths = [item["path"] for item in data["suggested_first_reads"]]
                self.assertIn("composer.json", paths)
                self.assertIn("src/Framework/Foundation/Application.php", paths)
                if "tests/Integration/Routing/RouteFixtureTest.php" in paths:
                    self.assertLess(paths.index("composer.json"), paths.index("tests/Integration/Routing/RouteFixtureTest.php"))
                    self.assertLess(
                        paths.index("src/Framework/Foundation/Application.php"),
                        paths.index("tests/Integration/Routing/RouteFixtureTest.php"),
                    )
            finally:
                os.chdir(previous)

    def test_overview_detects_python_framework_package_entry_points(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text("[project]\nname = 'frameworkish'\n", encoding="utf-8")
            package = root / "frameworkish" / "core" / "management"
            tests = root / "tests" / "management"
            docs = root / "docs"
            package.mkdir(parents=True)
            tests.mkdir(parents=True)
            docs.mkdir()
            (package / "__init__.py").write_text("def execute_from_command_line():\n    return None\n", encoding="utf-8")
            (package / "commands.py").write_text("def run_command():\n    return None\n", encoding="utf-8")
            (tests / "test_management.py").write_text("def test_management_command():\n    assert True\n", encoding="utf-8")
            (docs / "management.md").write_text("# Management commands\n", encoding="utf-8")
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["overview", "--json"]), 0)
                data = json.loads(output.getvalue())
                first_reads = [item["path"] for item in data["suggested_first_reads"]]
                entry_points = [item["path"] for item in data["entry_points"]]
                self.assertIn("frameworkish/core/management/__init__.py", first_reads)
                self.assertIn("frameworkish/core/management/__init__.py", entry_points)
                self.assertLess(
                    first_reads.index("frameworkish/core/management/__init__.py"),
                    first_reads.index("tests/management/test_management.py")
                    if "tests/management/test_management.py" in first_reads
                    else 99,
                )
            finally:
                os.chdir(previous)
