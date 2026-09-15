import json
import unittest

from job_assistant import ROOT, match
from job_sources import normalize_job


class DepartmentDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.profile = json.loads((ROOT / 'role_coverage.example.json').read_text())
        self.profile.update(skills=['SQL'], department_discovery={'enabled': True, 'terms': ['Product', 'Growth', 'Analytics', 'Decision Science']},
                            work_preferences={'hybrid_locations': ['Toronto']},
                            compensation={'currency': 'CAD', 'basis': 'total_cash', 'min': 175000, 'max': 200000})
        self.job = {'title': 'Manager, Insights', 'department': 'Product', 'description': 'Use SQL to lead experimentation.',
                    'location': 'Remote Canada', 'work_mode': 'remote', 'canada_eligible': 'true'}

    def test_ambiguous_title_admitted_only_in_discovery(self):
        result = match(self.job, self.profile, discovery=True)
        self.assertEqual(result['discovery_method'], 'department_and_description')
        self.assertIn('department: Product', result['discovery_evidence'])
        self.assertIsNone(match(self.job, self.profile))

    def test_title_and_team_can_supply_department_context(self):
        for changes in [{'title': 'Senior Manager, Product Insights', 'department': ''},
                        {'title': 'Decision Scientist', 'department': '', 'team': 'Growth'}]:
            with self.subTest(changes=changes):
                self.assertIsNotNone(match({**self.job, **changes}, self.profile, discovery=True))

    def test_department_alone_and_unrelated_roles_insufficient(self):
        for changes in [{'description': 'Partner with stakeholders'}, {'description': 'Use SQL'},
                        {'title': 'Software Engineer'}, {'title': 'Senior Backend Engineer, Analytics Instrumentation'}, {'title': 'Product Manager'},
                        {'department': 'Legal'}, {'title': 'Director, Insights'}, {'title': 'Junior Decision Scientist'}]:
            with self.subTest(changes=changes):
                self.assertIsNone(match({**self.job, **changes}, self.profile, discovery=True))

    def test_hard_filters_still_apply(self):
        for changes in [{'canada_eligible': 'false'}, {'work_mode': 'onsite'},
                        {'salary_min': '100000', 'salary_max': '150000', 'salary_currency': 'CAD', 'salary_period': 'annual', 'salary_basis': 'total_cash'}]:
            with self.subTest(changes=changes):
                self.assertIsNone(match({**self.job, **changes}, self.profile, discovery=True))

    def test_existing_title_score_unaffected(self):
        job = {**self.job, 'title': 'Senior Data Analyst'}
        self.assertEqual(match(job, self.profile)['score'], match({**job, 'department': 'Legal'}, self.profile)['score'])
        self.assertEqual(match(job, self.profile)['score'], match(job, self.profile, discovery=True)['score'])

    def test_adapter_preserves_departments_and_teams(self):
        gh = normalize_job({'title': 'Manager, Insights', 'absolute_url': 'https://example.com/1',
                            'departments': [{'name': 'Product'}, {'name': 'Analytics'}]},
                           {'type': 'greenhouse', 'board': 'example'}, 'today')
        self.assertEqual(gh['department'], 'Product; Analytics')
        ashby = normalize_job({'title': 'Decision Scientist', 'jobUrl': 'https://example.com/2',
                               'department': 'Data', 'team': 'Growth'},
                              {'type': 'ashby', 'board': 'example'}, 'today')
        self.assertEqual(ashby['team'], 'Growth')
        self.assertEqual(ashby['department'], 'Data')


if __name__ == '__main__':
    unittest.main()
