import time
import unittest

from jobradar.boards import parse_ats_url
from jobradar.discovery import candidate_slugs, harvest_boards_from_listings
from jobradar.models import Board
from jobradar.sources import ashby, greenhouse, hackernews, lever, trackers


class ParseAtsUrlTests(unittest.TestCase):
    def test_recognises_each_ats(self):
        self.assertEqual(
            parse_ats_url("https://job-boards.greenhouse.io/wurljobs/jobs/4731130006"),
            ("greenhouse", "wurljobs", "4731130006"),
        )
        self.assertEqual(
            parse_ats_url("https://boards.greenhouse.io/embed/job_app?for=figureai&token=55"),
            ("greenhouse", "figureai", None),
        )
        self.assertEqual(
            parse_ats_url("https://jobs.ashbyhq.com/skydio/0a1b2c3d-1111-2222-3333-444455556666?utm=x"),
            ("ashby", "skydio", "0a1b2c3d-1111-2222-3333-444455556666"),
        )
        self.assertEqual(
            parse_ats_url("https://jobs.lever.co/shieldai/0a1b2c3d-1111-2222-3333-444455556666/apply"),
            ("lever", "shieldai", "0a1b2c3d-1111-2222-3333-444455556666"),
        )
        self.assertIsNone(parse_ats_url("https://www.tesla.com/careers/search/job/123"))


class BoardParserTests(unittest.TestCase):
    def test_greenhouse(self):
        board = Board("greenhouse", "Acme", "Acme Robotics")
        payload = {"jobs": [{"id": 77, "title": " ML Intern ", "absolute_url": "https://x/77",
                             "location": {"name": "Seattle, WA"}, "updated_at": "2026-11-20T10:00:00-05:00"}]}
        (posting,) = greenhouse.parse_board_response(board, payload)
        self.assertEqual(posting.key, "greenhouse:acme:77")
        self.assertEqual(posting.title, "ML Intern")
        self.assertEqual(posting.locations, ["Seattle, WA"])
        self.assertEqual(posting.board_key, "greenhouse:acme")
        self.assertIsNotNone(posting.posted_at)

    def test_lever(self):
        board = Board("lever", "acme", "Acme")
        payload = [{"id": "abc", "text": "Software Engineer", "hostedUrl": "https://jobs.lever.co/acme/abc",
                    "categories": {"location": "Remote", "commitment": "Internship"},
                    "createdAt": 1795000000000, "descriptionPlain": "PyTorch"}]
        (posting,) = lever.parse_board_response(board, payload)
        self.assertEqual(posting.employment_type, "Internship")
        self.assertEqual(posting.posted_at, 1795000000)
        self.assertEqual(posting.locations, ["Remote"])

    def test_ashby_skips_unlisted_and_adds_remote(self):
        board = Board("ashby", "acme", "Acme")
        payload = {"jobs": [
            {"id": "1", "title": "Research Intern", "location": "San Francisco", "isRemote": True,
             "employmentType": "Intern", "publishedAt": "2026-11-20T18:00:00.000+00:00", "jobUrl": "https://j/1"},
            {"id": "2", "title": "Hidden", "isListed": False},
        ]}
        (posting,) = ashby.parse_board_response(board, payload)
        self.assertEqual(posting.locations, ["San Francisco", "Remote"])
        self.assertEqual(posting.employment_type, "Intern")


class TrackerTests(unittest.TestCase):
    def setUp(self):
        self.now = time.time()
        self.listing = {"id": "uuid-1", "company_name": "Wurl", "title": "Data Engineer Intern", "active": True,
                        "is_visible": True, "terms": ["N/A", "Summer 2027"], "date_posted": self.now - 3600,
                        "url": "https://job-boards.greenhouse.io/wurljobs/jobs/4731130006",
                        "locations": ["Remote in USA"], "degrees": ["Bachelor's"]}

    def test_reuses_ats_key_and_drops_placeholder_terms(self):
        (posting,) = trackers.parse_listings("simplify", [self.listing], self.now)
        self.assertEqual(posting.key, "greenhouse:wurljobs:4731130006")
        self.assertEqual(posting.terms, ["Summer 2027"])

    def test_skips_inactive_and_old(self):
        inactive = dict(self.listing, active=False)
        old = dict(self.listing, date_posted=self.now - 40 * 86400)
        self.assertEqual(trackers.parse_listings("simplify", [inactive, old], self.now), [])

    def test_harvest_boards(self):
        uuid_slug = dict(self.listing, url="https://jobs.ashbyhq.com/0a1b2c3d-1111-2222-3333-444455556666")
        boards = harvest_boards_from_listings("simplify", [self.listing, self.listing, uuid_slug], self.now)
        self.assertEqual([(board.ats, board.slug, board.company_name) for board in boards],
                         [("greenhouse", "wurljobs", "Wurl")])


class HackerNewsTests(unittest.TestCase):
    def test_parse_item(self):
        posting = hackernews.parse_item({"id": 9, "title": "Terranox AI (YC W26) Is Hiring a Summer AI/ML Intern",
                                         "time": 1795000000, "url": "https://example.com/job"})
        self.assertEqual(posting.company_name, "Terranox AI")
        self.assertEqual(posting.key, "hackernews:9")


class CandidateSlugTests(unittest.TestCase):
    def test_candidates(self):
        self.assertEqual(candidate_slugs("Physical Intelligence", ""), ["physicalintelligence", "physical-intelligence"])
        self.assertEqual(candidate_slugs("xAI", ""), [])


if __name__ == "__main__":
    unittest.main()
