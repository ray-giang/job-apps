import json
import unittest

from job_assistant import ROOT
from job_preferences import role_matches, compensation


class RoleCoverageTests(unittest.TestCase):
    def setUp(self):
        self.profile = json.loads((ROOT / 'role_coverage.example.json').read_text())

    def test_ic_seniority_and_unprefixed_titles(self):
        for title in ['Data Scientist', 'Senior Data Scientist, Product', 'Principal Data Scientist',
                      'Staff, Analytics Engineer', 'Lead Analytics Engineer', 'Data Analyst',
                      'Senior Product Analyst', 'Analytics Lead, Full Stack', 'Revenue Operations Analyst',
                      'Senior Business Analyst', 'Principal Insights Analyst', 'Growth Analyst',
                      'Senior Revenue Analyst', 'Business Intelligence Analyst', 'Analyst',
                      'Senior Analyst, Product', 'Analytics Lead', 'Data Engineer',
                      'Principal Data Engineer', 'Business Intelligence Engineer', 'Senior BI Engineer']:
            with self.subTest(title=title):
                self.assertIn('Data, analytics and BI IC', role_matches(title, self.profile))

    def test_management_titles(self):
        for title in ['Manager, Product Analytics', 'Senior Manager, Data Science', 'Senior Analytics Manager']:
            with self.subTest(title=title):
                self.assertEqual(role_matches(title, self.profile), ['Analytics/data science management'])

    def test_exclude_unrelated_junior_executive_and_temporary(self):
        for title in ['Junior Data Scientist', 'Data Analyst Intern', 'Director of Analytics',
                      'VP, Data Science', 'Product Manager', 'Senior Software Engineer',
                      'Contract Data Analyst', 'Head of Data Science']:
            with self.subTest(title=title):
                self.assertEqual(role_matches(title, self.profile), [])

    def test_base_minimum_does_not_exclude_unknown_bonus_above_floor(self):
        profile = {'compensation': {'currency': 'CAD', 'basis': 'total_cash', 'min': 175000, 'max': 200000, 'minimum_base_cad': 160000}}
        job = {'salary_min': '140000', 'salary_max': '159000', 'salary_currency': 'CAD', 'salary_period': 'annual', 'salary_basis': 'base'}
        self.assertFalse(compensation(job, profile)[0])
        self.assertTrue(compensation({**job, 'salary_max': '170000'}, profile)[0])


if __name__ == '__main__':
    unittest.main()
