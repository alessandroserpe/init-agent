from tests.support import *


class ExperimentsTests(InitAgentTestCase):
    def test_experiment_cases_manifest_is_valid(self) -> None:
        cases_path = Path(__file__).resolve().parents[1] / "experiments" / "cases.json"
        cases = json.loads(cases_path.read_text(encoding="utf-8"))
        self.assertGreater(len(cases), 0)
        for case in cases:
            self.assertIn("name", case)
            self.assertIn("repo", case)
            self.assertIn("query", case)
            self.assertIsInstance(case.get("expected_files"), list)
            self.assertIsInstance(case.get("noise_patterns"), list)

    def test_experiment_case_filter_loads_selected_case(self) -> None:
        cases = load_cases(["django-auth-session-middleware"])
        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0]["name"], "django-auth-session-middleware")

    def test_experiment_case_filter_loads_overview_case(self) -> None:
        cases = load_cases(["init-agent-repository-overview"])
        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0]["command"], "overview")

    def test_experiment_init_agent_case_falls_back_to_current_checkout(self) -> None:
        case = {
            "name": "init-agent-repository-overview",
            "repo": "/tmp/init-agent-bench-does-not-exist",
            "query": "repository overview",
        }
        self.assertEqual(resolve_case_repo(case), Path(__file__).resolve().parents[1])

    def test_experiment_case_filter_rejects_unknown_case(self) -> None:
        with self.assertRaises(SystemExit):
            load_cases(["not-a-real-benchmark-case"])

    def test_experiment_overview_case_uses_overview_candidates(self) -> None:
        case = {"command": "overview"}
        command = case_command(case)
        self.assertIn("--overview", command)
        paths = candidate_paths_for_case(
            case,
            {
                "overview": {
                    "suggested_first_reads": [{"path": "pyproject.toml"}],
                    "entry_points": [{"path": "src/app/cli.py"}],
                    "manifests": [{"path": "README.md"}],
                }
            },
        )
        self.assertEqual(paths, ["pyproject.toml", "src/app/cli.py", "README.md"])

    def test_scan_reduction_percent(self) -> None:
        self.assertEqual(scan_reduction_percent(100, 10), 90.0)
        self.assertEqual(scan_reduction_percent(3, 10), 0.0)
        self.assertIsNone(scan_reduction_percent(0, 10))
        self.assertIsNone(scan_reduction_percent(None, 10))

    def test_measure_indexed_file_read_uses_indexed_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text("[project]\nname = 'sample'\n", encoding="utf-8")
            (root / "app.py").write_text("def app():\n    return 'ok'\n", encoding="utf-8")
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                measurement = measure_indexed_file_read(root)
            finally:
                os.chdir(previous)
        self.assertIsNotNone(measurement)
        assert measurement is not None
        self.assertGreaterEqual(measurement["files"], 2)
        self.assertGreater(measurement["characters"], 0)
        self.assertGreaterEqual(measurement["elapsed_seconds"], 0.0)

    def test_experiment_summary_and_strict_thresholds(self) -> None:
        summary = summarize(
            [
                {
                    "status": "ok",
                    "top1_hit": True,
                    "top3_hit": True,
                    "top5_hit": True,
                    "noise_hit_count": 0,
                    "elapsed_seconds": 1.0,
                    "manual_scan_reduction_percent": 90.0,
                    "manual_scan_elapsed_seconds": 4.0,
                },
                {
                    "status": "ok",
                    "top1_hit": False,
                    "top3_hit": False,
                    "top5_hit": True,
                    "noise_hit_count": 1,
                    "elapsed_seconds": 2.0,
                    "manual_scan_reduction_percent": 80.0,
                    "manual_scan_elapsed_seconds": 6.0,
                },
            ]
        )
        self.assertEqual(summary["cases"], 2)
        self.assertEqual(summary["top3_rate"], 0.5)
        self.assertEqual(summary["top5_rate"], 1.0)
        self.assertEqual(summary["average_manual_scan_reduction_percent"], 85.0)
        self.assertEqual(summary["average_manual_scan_elapsed_seconds"], 5.0)
        args = argparse.Namespace(min_top3_rate=0.85, min_top5_rate=1.0, max_noise=2)
        failures = strict_failures_for(summary, args)
        self.assertIn("top3_rate 0.5 < 0.85", failures)
        self.assertNotIn("top5_rate 1.0 < 1.0", failures)

    def test_experiment_expected_ranks_csv_and_markdown_outputs(self) -> None:
        candidates = ["src/a.py", "src/b.py", "src/c.py"]
        expected = ["src/b.py", "src/missing.py"]
        self.assertEqual(expected_ranks(candidates, expected), {"src/b.py": 2, "src/missing.py": None})
        result = {
            "name": "sample",
            "status": "ok",
            "top1_hit": False,
            "top3_hit": True,
            "top5_hit": True,
            "expected_count": 2,
            "expected_hit_count": 1,
            "expected_file_ranks": expected_ranks(candidates, expected),
            "missing_expected_files": ["src/missing.py"],
            "noise_hit_count": 1,
            "candidate_file_count": 3,
            "elapsed_seconds": 0.25,
            "manual_scan_file_count": 30,
            "manual_scan_reduction_percent": 90.0,
        }
        row = result_csv_row(result)
        self.assertEqual(row["top1_hit"], "false")
        self.assertEqual(row["top3_hit"], "true")
        self.assertEqual(row["missing_expected_count"], 1)
        self.assertIn("src/b.py=2", row["expected_file_ranks"])
        self.assertIn("src/missing.py=missing", row["expected_file_ranks"])
        markdown = render_markdown_summary(
            {
                "summary": {
                    "cases": 1,
                    "top1_rate": 0.0,
                    "top3_rate": 1.0,
                    "top5_rate": 1.0,
                    "noise_hits": 1,
                    "average_elapsed_seconds": 0.25,
                    "average_manual_scan_reduction_percent": 90.0,
                },
                "results": [result],
                "skipped": [{"name": "missing-case", "reason": "missing repo"}],
            }
        )
        self.assertIn("# init-agent Benchmark Summary", markdown)
        self.assertIn("sample", markdown)
        self.assertIn("src/missing.py", markdown)
        self.assertIn("missing-case", markdown)

    def test_role_detection_does_not_treat_pytest_package_as_test(self) -> None:
        self.assertEqual(detect_role("src/_pytest/fixtures.py"), "source")
        self.assertEqual(detect_role("testing/python/fixtures.py"), "test")
        self.assertEqual(detect_role("src/pkg/test_example.py"), "test")
        self.assertEqual(detect_role("src/pkg/component.spec.ts"), "test")
