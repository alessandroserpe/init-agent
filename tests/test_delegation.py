from tests.support import *

from init_agent.agent_tools import (
    repo_reading_plan,
    repo_reading_plan_diff,
    repo_reading_plan_finish,
    repo_workstream_report,
    repo_workstream_review,
)
from init_agent.delegation import build_delegation_advice


def _plan_item(path: str, rank: int, confidence: str = "medium") -> dict[str, object]:
    return {
        "path": path,
        "rank": rank,
        "confidence": confidence,
        "read_priority": "read_now" if rank <= 3 else "read_if_needed",
        "action": "read",
        "tags": [],
    }


class DelegationTests(InitAgentTestCase):
    def test_small_high_confidence_plan_stays_direct(self) -> None:
        advice = build_delegation_advice(
            "change button color",
            [_plan_item("frontend/button.css", 1, "high"), _plan_item("tests/test_ui.py", 2, "high")],
            2,
        )
        self.assertEqual(advice["strategy"], "direct")
        self.assertFalse(advice["recommended"])
        self.assertEqual(advice["task_profile"]["model_tier"], "fast")
        self.assertEqual(advice["workstreams"], [])

    def test_multi_scope_plan_proposes_bounded_provider_agnostic_workstreams(self) -> None:
        advice = build_delegation_advice(
            "trace login failure across backend frontend and tests",
            [
                _plan_item("src/auth/session.py", 1),
                _plan_item("frontend/login.ts", 2),
                _plan_item("tests/test_login.py", 3),
                _plan_item("docs/auth.md", 4),
            ],
            3,
        )
        self.assertEqual(advice["strategy"], "parallel")
        self.assertTrue(advice["recommended"])
        self.assertGreaterEqual(len(advice["workstreams"]), 2)
        self.assertTrue(all(item["access_mode"] == "read_only" for item in advice["workstreams"]))
        self.assertTrue(advice["orchestrator_contract"]["must_review_reports"])
        self.assertNotIn("gpt", json.dumps(advice).lower())

    def test_report_requires_parent_review_before_plan_finish(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            _prepare_index(root)
            plan = repo_reading_plan(root, "debug login session across source tests and documentation", read_budget=3)
            workstreams = plan["delegation"]["workstreams"]
            self.assertTrue(workstreams)
            key = workstreams[0]["key"]

            reported = repo_workstream_report(
                root,
                plan["id"],
                key,
                "Inspected the assigned scope and identified the session validation path.",
                agent_name="explorer",
                files_read=["src/auth/session.py"],
                tests=["python3 -m unittest"],
                findings=["Session validation is implemented in src/auth/session.py."],
            )
            self.assertTrue(reported["updated"])
            self.assertEqual(reported["workstream"]["status"], "reported")
            plan_diff = repo_reading_plan_diff(root, plan["id"])
            self.assertIn("src/auth/session.py", plan_diff["diff"]["read_paths"])

            blocked = repo_reading_plan_finish(root, plan["id"], summary="premature finish")
            self.assertFalse(blocked["updated"])
            self.assertEqual(blocked["pending_review"][0]["key"], key)

            rework = repo_workstream_review(root, plan["id"], key, "rework", note="Verify the caller too.")
            self.assertTrue(rework["updated"])
            self.assertEqual(rework["workstream"]["status"], "rework")
            still_blocked = repo_reading_plan_finish(root, plan["id"], summary="still premature")
            self.assertFalse(still_blocked["updated"])

            repo_workstream_report(
                root,
                plan["id"],
                key,
                "Verified the implementation and its caller.",
                agent_name="explorer",
                files_read=["src/auth/session.py", "src/auth/login.py"],
            )
            accepted = repo_workstream_review(root, plan["id"], key, "accepted", note="Evidence checked by parent.")
            self.assertTrue(accepted["updated"])
            finished = repo_reading_plan_finish(
                root,
                plan["id"],
                read=["src/auth/session.py"],
                verified=["src/auth/session.py"],
                central=["src/auth/session.py"],
                summary="parent verified delegated evidence",
            )
            self.assertTrue(finished["updated"])
