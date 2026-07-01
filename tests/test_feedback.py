from tests.support import *


class FeedbackTests(InitAgentTestCase):
    def test_tokenize_query_splits_camel_case_acronyms_and_snake_case(self) -> None:
        raw_terms = identifier_terms("MCPServerStartup repoGraphSearch")
        self.assertIn("repo", raw_terms)
        tokens = tokenize_query("MCPServerStartup repoGraphSearch chat_intent_router.php")
        self.assertIn("mcp", tokens)
        self.assertIn("server", tokens)
        self.assertIn("startup", tokens)
        self.assertIn("graph", tokens)
        self.assertIn("search", tokens)
        self.assertIn("chat", tokens)
        self.assertIn("intent", tokens)
        self.assertIn("router", tokens)

    def test_feedback_add_and_list_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(
                        main(
                            [
                                "feedback",
                                "add",
                                "auth session bug",
                                "src/auth/session.py",
                                "--rating",
                                "useful",
                                "--reason",
                                "verified session state",
                                "--source",
                                "agent",
                                "--json",
                            ]
                        ),
                        0,
                    )
                record = json.loads(output.getvalue())
                self.assertEqual(record["path"], "src/auth/session.py")
                self.assertEqual(record["rating"], "useful")

                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["feedback", "list", "--json"]), 0)
                data = json.loads(output.getvalue())
                self.assertEqual(len(data["feedback"]), 1)
                self.assertEqual(data["feedback"][0]["reason"], "verified session state")
            finally:
                os.chdir(previous)

    def test_feedback_boosts_similar_context_query(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                main(
                    [
                        "feedback",
                        "add",
                        "authentication bug",
                        "src/auth/session.py",
                        "--rating",
                        "crucial",
                        "--reason",
                        "agent verified session handling",
                    ]
                )
                pack = build_context_pack(root, "authentication bug")
                self.assertEqual(pack["candidate_files"][0]["path"], "src/auth/session.py")
                self.assertIn("previously marked crucial for similar query", pack["candidate_files"][0]["reasons"])
            finally:
                os.chdir(previous)

    def test_feedback_does_not_overfit_unrelated_query(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                main(["feedback", "add", "authentication bug", "src/auth/session.py", "--rating", "crucial"])
                pack = build_context_pack(root, "billing invoice export")
                paths = [item["path"] for item in pack["candidate_files"]]
                self.assertNotIn("src/auth/session.py", paths)
            finally:
                os.chdir(previous)

    def test_feedback_noisy_penalizes_similar_context_query(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                main(["feedback", "add", "login session", "src/auth/login.py", "--rating", "noisy"])
                pack = build_context_pack(root, "login session")
                login = next(item for item in pack["candidate_files"] if item["path"] == "src/auth/login.py")
                self.assertIn("previously marked noisy for similar query", login["reasons"])
            finally:
                os.chdir(previous)

    def test_feedback_explain_json_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                main(
                    [
                        "feedback",
                        "add",
                        "login session",
                        "src/auth/session.py",
                        "--rating",
                        "crucial",
                        "--reason",
                        "verified session flow",
                    ]
                )
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["feedback", "explain", "login session", "--json"]), 0)
                data = json.loads(output.getvalue())
                self.assertEqual(data["query"], "login session")
                self.assertIn("login", data["query_tokens"])
                self.assertEqual(data["signals"][0]["path"], "src/auth/session.py")
                self.assertGreater(data["signals"][0]["boost"], 0)
                self.assertEqual(data["signals"][0]["items"][0]["rating"], "crucial")
                self.assertIn("similarity", data["signals"][0]["items"][0])
                self.assertIn("contribution", data["signals"][0]["items"][0])
            finally:
                os.chdir(previous)

    def test_feedback_explain_reports_source_weight(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                main(
                    [
                        "feedback",
                        "add",
                        "login session",
                        "src/auth/session.py",
                        "--rating",
                        "useful",
                        "--source",
                        "user",
                    ]
                )
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["feedback", "explain", "login session", "--json"]), 0)
                data = json.loads(output.getvalue())
                item = data["signals"][0]["items"][0]
                self.assertEqual(item["source"], "user")
                self.assertEqual(item["source_weight"], 1.2)
                self.assertEqual(item["contribution"], 12.0)
                self.assertEqual(data["signals"][0]["boost"], 12.0)
            finally:
                os.chdir(previous)

    def test_feedback_missing_contributes_to_explain_and_ranking(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            internal_dir = root / "src" / "internal"
            internal_dir.mkdir(parents=True)
            (internal_dir / "state.py").write_text("def mark_read():\n    return True\n", encoding="utf-8")
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                main(
                    [
                        "feedback",
                        "add",
                        "login session",
                        "src/internal/state.py",
                        "--rating",
                        "missing",
                        "--source",
                        "agent",
                    ]
                )

                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["feedback", "explain", "login", "session", "--json"]), 0)
                data = json.loads(output.getvalue())
                self.assertEqual(data["signals"][0]["path"], "src/internal/state.py")
                self.assertEqual(data["signals"][0]["boost"], 8.0)
                self.assertEqual(data["signals"][0]["items"][0]["rating"], "missing")
                self.assertEqual(data["signals"][0]["items"][0]["contribution"], 8.0)

                pack = build_context_pack(root, "login session")
                state = next(item for item in pack["candidate_files"] if item["path"] == "src/internal/state.py")
                self.assertIn("previously marked missing from similar query", state["reasons"])
            finally:
                os.chdir(previous)

    def test_feedback_explain_accepts_unquoted_query_words(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                main(["feedback", "add", "login session", "src/auth/session.py", "--rating", "useful"])
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["feedback", "explain", "login", "session", "--json"]), 0)
                data = json.loads(output.getvalue())
                self.assertEqual(data["query"], "login session")
                self.assertEqual(data["signals"][0]["path"], "src/auth/session.py")
            finally:
                os.chdir(previous)

    def test_feedback_explain_can_show_ignored_items(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                main(["feedback", "add", "billing invoice", "src/auth/session.py", "--rating", "useful"])

                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["feedback", "explain", "login session", "--json"]), 0)
                data = json.loads(output.getvalue())
                self.assertEqual(data["signals"], [])
                self.assertEqual(data["ignored"], [])

                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["feedback", "explain", "login", "session", "--all", "--json"]), 0)
                data = json.loads(output.getvalue())
                self.assertEqual(data["signals"], [])
                self.assertEqual(data["ignored"][0]["path"], "src/auth/session.py")
                self.assertEqual(data["ignored"][0]["ignored_reason"], "similarity below threshold")
            finally:
                os.chdir(previous)

    def test_feedback_explain_does_not_match_unrelated_item_on_same_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                main(["feedback", "add", "login session", "src/auth/session.py", "--rating", "useful"])
                main(["feedback", "add", "billing invoice", "src/auth/session.py", "--rating", "useful"])
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["feedback", "explain", "login", "session", "--all", "--json"]), 0)
                data = json.loads(output.getvalue())
                matched_queries = [item["query"] for item in data["signals"][0]["items"]]
                ignored_queries = [item["query"] for item in data["ignored"]]
                self.assertEqual(matched_queries, ["login session"])
                self.assertIn("billing invoice", ignored_queries)
            finally:
                os.chdir(previous)

    def test_feedback_noisy_demotes_strong_direct_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                main(["feedback", "add", "login session", "src/auth/login.py", "--rating", "noisy"])
                main(["feedback", "add", "login session", "src/auth/session.py", "--rating", "useful"])
                pack = build_context_pack(root, "login session")
                paths = [item["path"] for item in pack["candidate_files"]]
                self.assertLess(paths.index("src/auth/session.py"), paths.index("src/auth/login.py"))
                login = next(item for item in pack["candidate_files"] if item["path"] == "src/auth/login.py")
                self.assertLess(login["score"], 0.75)
            finally:
                os.chdir(previous)

    def test_feedback_crucial_surfaces_verified_file_without_direct_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            internal_dir = root / "src" / "internal"
            internal_dir.mkdir(parents=True)
            (internal_dir / "state.py").write_text("def mark_read():\n    return True\n", encoding="utf-8")
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                main(["feedback", "add", "login session", "src/internal/state.py", "--rating", "crucial"])
                pack = build_context_pack(root, "login session")
                paths = [item["path"] for item in pack["candidate_files"]]
                self.assertIn("src/internal/state.py", paths)
                state = next(item for item in pack["candidate_files"] if item["path"] == "src/internal/state.py")
                self.assertIn("previously marked crucial for similar query", state["reasons"])
            finally:
                os.chdir(previous)

    def test_feedback_improves_relative_rank_without_absolute_position(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            internal_dir = root / "src" / "internal"
            internal_dir.mkdir(parents=True)
            (internal_dir / "state.py").write_text("def mark_read():\n    return True\n", encoding="utf-8")
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                before = build_context_pack(root, "login session")
                before_paths = [item["path"] for item in before["candidate_files"]]
                before_rank = before_paths.index("src/internal/state.py") if "src/internal/state.py" in before_paths else 99
                main(["feedback", "add", "login session", "src/internal/state.py", "--rating", "crucial"])
                after = build_context_pack(root, "login session")
                after_paths = [item["path"] for item in after["candidate_files"]]
                self.assertIn("src/internal/state.py", after_paths)
                self.assertLess(after_paths.index("src/internal/state.py"), before_rank)
            finally:
                os.chdir(previous)

    def test_feedback_export_import_and_clear(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                main(["feedback", "add", "login bug", "src/auth/login.py", "--rating", "useful"])
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["feedback", "export", "--json"]), 0)
                exported = json.loads(output.getvalue())
                self.assertEqual(len(exported["feedback"]), 1)

                export_path = root / "feedback.json"
                export_path.write_text(json.dumps(exported), encoding="utf-8")
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["feedback", "clear", "--all", "--json"]), 0)
                self.assertEqual(json.loads(output.getvalue())["deleted"], 1)

                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["feedback", "import", str(export_path), "--json"]), 0)
                self.assertEqual(json.loads(output.getvalue())["imported"], 1)
            finally:
                os.chdir(previous)
