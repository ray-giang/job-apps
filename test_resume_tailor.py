import unittest

from resume_tailor import select_resume


class ResumeTailoringTests(unittest.TestCase):
    def test_selects_only_master_evidence_and_prefers_relevant_bullets(self):
        master = {
            "contact": {"name": "Example"}, "headline_options": {"marketing": "Marketing Leader", "general": "Analytics"},
            "summary_facts": ["Known fact"], "skills": ["SQL", "Marketing Attribution"], "education": [],
            "experience": [{"company": "A", "title": "Analyst", "start": "2020", "end": "Present", "bullets": [
                {"id": "marketing", "text": "Built a marketing attribution model.", "tags": ["marketing", "attribution"]},
                {"id": "operations", "text": "Improved an operations report.", "tags": ["operations"]}
            ]}]
        }
        job = {"title": "Marketing Science Lead", "company": "B", "description": "Marketing attribution and measurement"}
        result = select_resume(master, job, max_bullets=1)
        self.assertEqual(result["track"], "marketing")
        self.assertEqual(result["evidence_ids"], ["marketing"])
        self.assertEqual(result["experience"][0]["bullets"][0]["text"], master["experience"][0]["bullets"][0]["text"])
        self.assertLessEqual(len("| " + " | ".join(result["skills"]) + " |"), 235)


if __name__ == "__main__":
    unittest.main()
