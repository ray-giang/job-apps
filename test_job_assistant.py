import argparse
import tempfile
import unittest
from pathlib import Path

from job_assistant import ROOT, load_profile, match, read_csv, track
from job_preferences import compensation, role_matches


class MatchingTests(unittest.TestCase):
    def setUp(self):
        # Public fixtures keep tests independent of personal profile edits.
        self.profile = {
            "roles": ["Staff Data Analyst"], "skills": ["SQL"],
            "role_tracks": [{"name": "IC", "patterns": [r"\b(?:lead|staff)\b.*\b(?:data analyst|analytics engineer)\b"]},
                            {"name": "Manager", "patterns": [r"\bmanager\b.*\banalytics\b"]}],
            "work_preferences": {"hybrid_locations": ["Toronto"]},
            "compensation": {"currency": "CAD", "basis": "total_cash", "min": 175000, "max": 200000},
        }
        self.job = {"title": "Staff Data Analyst", "location": "Canada", "description": "SQL",
                    "work_mode": "remote", "canada_eligible": "true", "salary_min": "175000",
                    "salary_max": "200000", "salary_currency": "CAD", "salary_period": "annual", "salary_basis": "total_cash"}

    def test_remote_preferred_to_toronto_hybrid(self):
        remote = match(self.job, self.profile)
        hybrid = match({**self.job, "work_mode": "hybrid", "location": "Toronto"}, self.profile)
        self.assertGreater(remote["score"], hybrid["score"])

    def test_ineligible_locations_and_work_modes(self):
        for changes in ({"canada_eligible": "false"}, {"work_mode": "onsite"}, {"work_mode": "hybrid", "location": "Vancouver"}):
            with self.subTest(changes=changes):
                self.assertIsNone(match({**self.job, **changes}, self.profile))

    def test_unknown_remote_eligibility_flagged(self):
        result = match({**self.job, "canada_eligible": ""}, self.profile)
        self.assertIn("Verify remote hiring", result["review_notes"])

    def test_below_cash_target_excluded_but_bonus_unknown_kept(self):
        job = {**self.job, "salary_min": "150000", "salary_max": "165000"}
        self.assertIsNone(match(job, self.profile))
        result = match({**job, "salary_basis": "base"}, self.profile)
        self.assertEqual(result["compensation_status"], "review")

    def test_range_overlap_and_above_target(self):
        result = match({**self.job, "salary_min": "160000", "salary_max": "180000"}, self.profile)
        self.assertEqual(result["compensation_status"], "partly_meets_target")
        result = match({**self.job, "salary_min": "210000", "salary_max": "230000"}, self.profile)
        self.assertEqual(result["compensation_status"], "above_target")

    def test_noncomparable_and_invalid_pay_flagged(self):
        for changes in ({"salary_currency": "USD"}, {"salary_period": "hourly"}, {"salary_basis": "total_comp"}, {"salary_min": "nan"}, {"salary_min": "250000"}):
            with self.subTest(changes=changes):
                result = compensation({**self.job, **changes}, self.profile)
                self.assertTrue(result[0])
                self.assertEqual(result[2], "review")

    def test_missing_pay_retained(self):
        result = match({**self.job, "salary_min": "", "salary_max": ""}, self.profile)
        self.assertEqual(result["compensation_status"], "undisclosed")

    def test_junior_excluded_even_if_description_mentions_staff(self):
        self.assertIsNone(match({**self.job, "title": "Junior Data Analyst", "description": "Work with staff data analysts using SQL"}, self.profile))
        self.assertTrue(role_matches("Manager, Product Analytics", self.profile))

    def test_original_profile_still_works(self):
        profile = load_profile(ROOT / "profile.example.json")
        jobs = read_csv(ROOT / "jobs.example.csv", ["title"])
        self.assertEqual(match(jobs[0], profile)["score"], 100)
        self.assertIsNone(match(jobs[1], profile))
        self.assertIsNone(match(jobs[2], profile))

    def test_tracking_preserves_notes(self):
        with tempfile.TemporaryDirectory() as directory:
            args = argparse.Namespace(tracker=Path(directory) / "tracker.csv", url="https://example.com/1", company="Example", title="Analyst", status="saved", notes="Keep")
            track(args)
            args.company = args.title = args.notes = None
            args.status = "applied"
            track(args)
            rows = read_csv(args.tracker, ["url"])
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["notes"], "Keep")
            self.assertEqual(rows[0]["status"], "applied")


if __name__ == "__main__":
    unittest.main()
