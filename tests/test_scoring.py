import tomllib
import unittest
from datetime import date
from pathlib import Path

from jobradar.models import JobPosting
from jobradar.scoring import is_internship, score_job

PROFILE = tomllib.loads((Path(__file__).resolve().parent.parent / "config" / "profile.toml").read_text())
DIRECTORY = {
    "tinyrobots": {"is_ai": True, "is_startup": True},
    "bigailab": {"is_ai": True, "is_startup": False},
}
TODAY = date(2026, 11, 20)
INSTANT = PROFILE["alerts"]["instant_threshold"]
DIGEST = PROFILE["alerts"]["digest_threshold"]


def make_job(title, company="Generic Corp", **fields):
    return JobPosting(key=f"test:{title}", source="test", company_name=company, title=title, url="https://x", **fields)


def score(title, company="Generic Corp", **fields):
    return score_job(make_job(title, company, **fields), PROFILE, DIRECTORY, TODAY)


class InternshipFilterTests(unittest.TestCase):
    def test_titles(self):
        self.assertTrue(is_internship(make_job("Machine Learning Intern"), PROFILE))
        self.assertTrue(is_internship(make_job("Software Engineering Co-op"), PROFILE))
        self.assertTrue(is_internship(make_job("Software Engineer", employment_type="Intern"), PROFILE))
        self.assertFalse(is_internship(make_job("Internal Tools Engineer"), PROFILE))
        self.assertFalse(is_internship(make_job("International Sales Lead"), PROFILE))


class ScoringTests(unittest.TestCase):
    def test_ml_and_robotics_roles_are_instant_anywhere(self):
        self.assertGreaterEqual(score("Machine Learning Engineer Intern").score, INSTANT)
        self.assertGreaterEqual(score("Reinforcement Learning Intern").score, INSTANT)
        self.assertGreater(score("Robotics Software Intern").score, score("AI Engineer Intern").score)

    def test_plain_swe_depends_on_company(self):
        self.assertLess(score("Software Engineer Intern").score, DIGEST)
        self.assertGreaterEqual(score("Software Engineer Intern", "Tiny Robots").score, INSTANT)
        big_lab_score = score("Software Engineer Intern", "Big AI Lab").score
        self.assertTrue(DIGEST <= big_lab_score < INSTANT)

    def test_startup_ranks_above_big_company_for_same_role(self):
        self.assertGreater(score("ML Intern", "Tiny Robots").score, score("ML Intern", "Big AI Lab").score)

    def test_exclusions(self):
        self.assertIsNotNone(score("Marketing Intern", "Tiny Robots").excluded_because)
        self.assertIsNotNone(score("PhD Research Intern - Machine Learning").excluded_because)
        self.assertIsNotNone(score("ML Intern - Summer 2026").excluded_because)
        self.assertIsNone(score("ML Intern - Summer 2027").excluded_because)
        self.assertIsNone(score("ML Intern (Winter 2026-27)").excluded_because)
        self.assertIsNotNone(score("ML Intern", locations=["London, UK"]).excluded_because)
        self.assertIsNone(score("ML Intern", locations=["London, UK", "New York, NY"]).excluded_because)
        self.assertIsNotNone(score("ML Intern", degrees=["Master's", "PhD"]).excluded_because)
        self.assertIsNone(score("ML Intern", degrees=["Bachelor's", "Master's"]).excluded_because)
        self.assertIsNotNone(score("Business Operations Intern").excluded_because)
        self.assertIsNone(score("ML Operations Intern").excluded_because)

    def test_graduate_only_postings_are_dropped(self):
        phd_only = "Requirements: currently pursuing a PhD in Computer Science or a related field."
        masters_only = "You are enrolled in a Master's program (M.S.) in CS."
        open_to_all = "Pursuing a BS, MS, or PhD in Computer Science."
        undergraduate = "Currently enrolled in an undergraduate program; graduate students also welcome."
        self.assertIsNotNone(score("ML Intern", description=phd_only).excluded_because)
        self.assertIsNotNone(score("ML Intern", description=masters_only).excluded_because)
        self.assertIsNone(score("ML Intern", description=open_to_all).excluded_because)
        self.assertIsNone(score("ML Intern", description=undergraduate).excluded_because)
        self.assertIsNone(score("ML Intern", description="Build models with PyTorch.").excluded_because)
        self.assertIsNone(score("ML Intern", description=phd_only, degrees=["Bachelor's"]).excluded_because)
        self.assertIsNotNone(score("Graduate Machine Learning Intern").excluded_because)
        self.assertIsNone(score("Undergraduate Machine Learning Intern").excluded_because)

    def test_scientist_titles_need_an_undergraduate_signal(self):
        self.assertIsNotNone(score("Research Scientist Intern - Robotics").excluded_because)
        self.assertIsNotNone(score("Applied Scientist Intern").excluded_because)
        self.assertIsNone(score("Research Scientist Intern", degrees=["Bachelor's", "PhD"]).excluded_because)
        self.assertIsNone(score("Research Scientist Intern", description="Open to undergraduates.").excluded_because)
        self.assertIsNone(score("Research Engineer Intern").excluded_because)
        self.assertIsNone(score("Data Scientist Intern", description="BS or MS students").excluded_because)

    def test_description_and_location_bonuses(self):
        plain = score("AI Intern").score
        with_description = score("AI Intern", description="We train PyTorch policies with reinforcement learning").score
        with_location = score("AI Intern", locations=["Seattle, WA"]).score
        self.assertGreater(with_description, plain)
        self.assertEqual(with_location, plain + PROFILE["location"]["preferred_bonus"])


if __name__ == "__main__":
    unittest.main()
