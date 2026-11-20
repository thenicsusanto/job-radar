import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from jobradar import cli
from jobradar import state as state_store
from jobradar.models import JobPosting


def make_posting(key, title, company="Generic Corp", board_key=None, source="simplify"):
    return JobPosting(key=key, source=source, company_name=company, title=title, url=f"https://x/{key}",
                      posted_at=time.time(), board_key=board_key)


class PollFlowTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.state_path = Path(self.temporary_directory.name) / "state.json"
        self.sent_emails = []

    def tearDown(self):
        self.temporary_directory.cleanup()

    def run_poll_with(self, postings, responding_board_keys=(), send_side_effect=None):
        def fake_send(kind, intro, scored_jobs, dry_run=False):
            if send_side_effect:
                raise send_side_effect
            self.sent_emails.append((kind, [scored.job.title for scored in scored_jobs]))

        pending = {"tracker_etags": {}, "hackernews_examined_ids": None}
        with mock.patch.object(cli, "collect_postings", return_value=(postings, list(responding_board_keys), pending)), \
             mock.patch.object(cli.emailer, "send_email", side_effect=fake_send), \
             mock.patch.object(cli, "load_boards", return_value=[]), \
             mock.patch.object(cli.discovery, "load_directory", return_value={}):
            return cli.run_poll(self.state_path, dry_run=False)

    def test_first_run_sends_baseline_then_only_new_jobs(self):
        existing = [make_posting("a:1", "Machine Learning Intern"), make_posting("a:2", "Senior Engineer")]
        self.run_poll_with(existing)
        self.assertEqual(self.sent_emails, [("baseline", ["Machine Learning Intern"])])

        self.sent_emails.clear()
        self.run_poll_with(existing)
        self.assertEqual(self.sent_emails, [])

        new_postings = existing + [
            make_posting("a:3", "Robotics Intern"),
            make_posting("a:4", "Data Science Intern"),
            make_posting("a:5", "Marketing Intern"),
        ]
        self.run_poll_with(new_postings)
        self.assertEqual(self.sent_emails, [("instant", ["Robotics Intern"])])
        state = state_store.load_state(self.state_path)
        self.assertEqual([entry["job"]["title"] for entry in state["digest_queue"]], ["Data Science Intern"])
        self.assertIn("a:5", state["seen_job_keys"])

        self.sent_emails.clear()
        with mock.patch.object(cli.emailer, "send_email",
                               side_effect=lambda kind, intro, jobs, dry_run=False: self.sent_emails.append(kind)):
            cli.run_digest(self.state_path, dry_run=False)
        self.assertEqual(self.sent_emails, ["digest"])
        self.assertEqual(state_store.load_state(self.state_path)["digest_queue"], [])

    def test_same_role_from_two_sources_alerts_once(self):
        self.run_poll_with([])
        ats_copy = make_posting("greenhouse:acme:1", "ML Intern", "Acme", board_key="greenhouse:acme", source="greenhouse")
        self.run_poll_with([ats_copy], responding_board_keys=["greenhouse:acme"])  # new board: digest
        self.sent_emails.clear()
        tracker_copy = make_posting("simplify:zzz", "ML Intern", "Acme")
        self.run_poll_with([ats_copy, tracker_copy], responding_board_keys=["greenhouse:acme"])
        self.assertEqual(self.sent_emails, [])

    def test_jobs_from_newly_tracked_board_go_to_digest_not_instant(self):
        self.run_poll_with([])
        posting = make_posting("ashby:new:1", "ML Intern", "NewCo", board_key="ashby:new", source="ashby")
        self.run_poll_with([posting], responding_board_keys=["ashby:new"])
        self.assertEqual(self.sent_emails, [])
        self.assertEqual(len(state_store.load_state(self.state_path)["digest_queue"]), 1)
        later_posting = make_posting("ashby:new:2", "Robotics Intern", "NewCo", board_key="ashby:new", source="ashby")
        self.run_poll_with([posting, later_posting], responding_board_keys=["ashby:new"])
        self.assertEqual(self.sent_emails, [("instant", ["Robotics Intern"])])

    def test_failed_email_is_retried_next_run(self):
        self.run_poll_with([])
        posting = make_posting("a:9", "ML Intern")
        with self.assertRaises(RuntimeError):
            self.run_poll_with([posting], send_side_effect=RuntimeError("smtp down"))
        self.run_poll_with([posting])
        self.assertEqual(self.sent_emails, [("instant", ["ML Intern"])])


if __name__ == "__main__":
    unittest.main()
