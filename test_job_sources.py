import argparse
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from job_assistant import ROOT, read_csv
from job_sources import collect, collection_assessment, endpoint, fetch, fetch_amazon, fetch_careers_html, fetch_workday, location_fields, normalize_job, plain, salary_fields


class SourceTests(unittest.TestCase):
    def test_html_and_encoded_greenhouse_content(self):
        self.assertEqual(plain('&lt;p&gt;SQL &amp;amp; dbt&lt;/p&gt;<script>bad()</script>'), 'SQL & dbt')

    def test_salary_requires_explicit_currency_period_and_basis(self):
        salary = salary_fields('Annual base salary: CAD 175,000 – 200,000')
        self.assertEqual(salary['salary_min'], 175000)
        self.assertEqual(salary['salary_basis'], 'base')
        self.assertEqual(salary_fields('$175,000 - $200,000 per year')['salary_min'], '')
        self.assertEqual(salary_fields('CAD 175,000 - 200,000')['salary_min'], 175000)
        self.assertEqual(salary_fields('Annual USD 150,000 - 180,000 / CAD 170,000 - 200,000')['salary_min'], 170000)
        self.assertEqual(salary_fields('CAN base pay range per year: $145,000 - $205,000')['salary_max'], 205000)
        self.assertEqual(salary_fields('CA$95K - CA$143.75K')['salary_min'], 95000)
        self.assertEqual(salary_fields('Canada: the pay range is $180,000 to $247,500 per year')['salary_min'], 180000)
        jane = salary_fields('Compensation & Benefits\nOur salary bands are intentionally wide.\n🇨🇦 Canada: $152,000 – $237,500 (accomplished: ~$180,500 CAD)\n🇺🇸 United States: $149,600 – $215,100 USD')
        self.assertEqual(jane['salary_min'], 152000)
        self.assertEqual(jane['salary_max'], 237500)
        self.assertEqual(jane['salary_extraction_confidence'], 'context')
        jane_location = salary_fields('This role has an annual salary range of $152,000 to $237,500. Most new hires join at $180,500.', 'Canada')
        self.assertEqual(jane_location['salary_min'], 152000)
        self.assertEqual(jane_location['salary_max'], 237500)
        self.assertEqual(jane_location['salary_currency'], 'CAD')
        self.assertEqual(jane_location['salary_extraction_confidence'], 'context')
        self.assertEqual(salary_fields('$114,000—$142,500 CAD\n$176,000—$220,000 CAD')['salary_extraction_confidence'], 'ambiguous')
        self.assertEqual(salary_fields('Annual compensation CAD 175k - 200k')['salary_basis'], '')

    def test_unparsed_pay_is_review_not_undisclosed(self):
        from job_preferences import compensation
        result = compensation({'salary_raw': 'CAN base pay range per year: $145,000 - $205,000'},
                              {'compensation': {'currency': 'CAD', 'basis': 'total_cash', 'min': 175000, 'max': 200000}})
        self.assertEqual(result[2], 'review')

    def test_restricted_and_ambiguous_locations(self):
        self.assertEqual(location_fields('Remote - Canada')['canada_eligible'], 'true')
        self.assertEqual(location_fields('Remote - US')['canada_eligible'], 'false')
        self.assertEqual(location_fields('Remote - British Columbia, Canada')['canada_eligible'], '')
        self.assertEqual(location_fields('Remote - North America')['canada_eligible'], '')
        self.assertEqual(location_fields('Toronto (Hybrid)')['work_mode'], 'hybrid')

    def test_normalize_sources_and_unlisted_jobs(self):
        source = {'type': 'greenhouse', 'board': 'example', 'company': 'Example'}
        job = normalize_job({'id': 1, 'title': 'Staff Data Analyst', 'absolute_url': 'https://example.com/1', 'location': {'name': 'Remote - Canada'}, 'content': '<p>SQL</p>'}, source, 'today')
        self.assertEqual(job['description'], 'SQL')
        self.assertEqual(job['source'], 'greenhouse: Example')
        self.assertEqual(job['salary_min'], '')
        self.assertIsNone(normalize_job({'isListed': False}, {'type': 'ashby'}, 'today'))
        remote = normalize_job({'title': 'Staff Data Analyst', 'url': 'https://remotive.com/1', 'company_name': 'Example', 'candidate_required_location': 'Worldwide'}, {'type': 'remotive'}, 'today')
        self.assertEqual(remote['source'], 'Remotive')
        self.assertEqual(remote['work_mode'], 'remote')

    def test_lever_endpoint_and_normalization(self):
        source = {'type': 'lever', 'board': 'example', 'company': 'Example'}
        self.assertEqual(endpoint(source), 'https://api.lever.co/v0/postings/example?mode=json')
        item = {'id': 'abc', 'text': 'Manager, Insights', 'hostedUrl': 'https://jobs.lever.co/example/abc',
                'workplaceType': 'remote', 'categories': {'location': 'Remote - Canada', 'allLocations': ['Remote - Canada'],
                                                          'department': 'Data', 'team': 'Product Analytics'},
                'descriptionPlain': 'Lead product analytics with SQL.', 'lists': [{'text': 'What you will do', 'content': '<li>Experimentation</li>'}],
                'additionalPlain': 'Permanent full-time role'}
        job = normalize_job(item, source, 'today')
        self.assertEqual(job['department'], 'Data')
        self.assertEqual(job['team'], 'Product Analytics')
        self.assertEqual(job['canada_eligible'], 'true')
        self.assertIn('Experimentation', job['description'])

    def test_ashby_slug_patch_encodes_spaces_and_keeps_dots(self):
        self.assertEqual(endpoint({'type': 'ashby', 'board': 'Blackpoint Cyber'}),
                         'https://api.ashbyhq.com/posting-api/job-board/Blackpoint%20Cyber?includeCompensation=true')
        self.assertIn('/hive.co?', endpoint({'type': 'ashby', 'board': 'hive.co'}))

    @patch('job_sources.read_json')
    def test_workday_paginates_and_enriches_summaries(self, read_json):
        read_json.side_effect = [
            {'total': 1, 'jobPostings': [{'title': 'Lead Product Analyst', 'externalPath': '/job/Toronto/Lead_JR1'}]},
            {'jobPostingInfo': {'title': 'Lead Product Analyst', 'location': 'Canada - Remote',
                                'jobDescription': '<p>SQL and experimentation</p>', 'externalUrl': 'https://example.com/JR1'}},
        ]
        source = {'type': 'workday', 'company': 'Example', 'url': 'https://example.com/wday/cxs/x/site/jobs', 'query': 'data'}
        data = fetch_workday(source)
        self.assertEqual(data['jobs'][0]['jobUrl'], 'https://example.com/JR1')
        self.assertEqual(normalize_job(data['jobs'][0], source, 'today')['canada_eligible'], 'true')

    @patch('job_sources.read_json')
    def test_amazon_adapter_paginates(self, read_json):
        read_json.return_value = {'hits': 1, 'jobs': [{'id_icims': '1', 'title': 'Data Manager',
            'location': 'CAN, ON, Toronto', 'job_path': '/en/jobs/1/data-manager', 'description': 'Product analytics'}]}
        source = {'type': 'amazon', 'company': 'Amazon', 'url': 'https://www.amazon.jobs/en/search.json?base_query=data', 'max_results': 10}
        job = normalize_job(fetch_amazon(source)['jobs'][0], source, 'today')
        self.assertEqual(job['url'], 'https://www.amazon.jobs/en/jobs/1/data-manager')

    @patch('job_sources.read_text')
    def test_html_adapter_extracts_and_deduplicates_job_links(self, read_text):
        read_text.side_effect = ['<a href="/careers/data_lead_123">Data</a><a href="/careers/data_lead_123">Data</a>',
                                 '<h1>Lead Data Analyst</h1><p>Remote Canada product analytics</p>']
        source = {'type': 'careers_html', 'company': 'Example', 'url': 'https://example.com/careers',
                  'link_pattern': r'(/careers/[^" ]+)', 'max_results': 5}
        self.assertEqual(len(fetch_careers_html(source)['jobs']), 1)

    def test_collection_confidence_requires_analytical_evidence_for_analysts(self):
        from job_assistant import load_profile, match
        profile = load_profile(ROOT / 'profile.json')
        base = dict.fromkeys(__import__('job_sources').FIELDS, '')
        base.update(title='Senior Analyst', company='Example', location='Remote - Canada', remote='true',
                    work_mode='remote', canada_eligible='true', url='https://example.com/role')
        weak = collection_assessment(base, profile, match(base, profile, discovery=True))
        self.assertEqual(weak['collection_decision'], 'rejected')
        strong_row = {**base, 'description': 'Use SQL, experimentation, metrics, and product analytics.'}
        strong = collection_assessment(strong_row, profile, match(strong_row, profile, discovery=True))
        self.assertEqual(strong['collection_decision'], 'admitted')
        self.assertEqual(strong['role_confidence'], 40)
        self.assertEqual(strong['compensation_confidence'], 4)
        upper_range = {**strong_row, 'salary_min': '145000', 'salary_max': '205000',
                       'salary_currency': 'CAD', 'salary_period': 'annual', 'salary_basis': 'base'}
        scored = collection_assessment(upper_range, profile, match(upper_range, profile, discovery=True))
        self.assertEqual(scored['compensation_confidence'], 10)

    def test_collection_rejects_remote_regions_that_exclude_canada(self):
        from job_assistant import load_profile, match
        profile = load_profile(ROOT / 'profile.json')
        base = dict.fromkeys(__import__('job_sources').FIELDS, '')
        base.update(title='Staff Data Analyst', company='Example', description='SQL product analytics experimentation',
                    location='Germany | Remote', remote='true', work_mode='remote', url='https://example.com/de')
        rejected = collection_assessment(base, profile, match(base, profile, discovery=True))
        self.assertEqual(rejected['collection_decision'], 'rejected')
        canada = {**base, 'location': 'Remote - US; Remote - Canada', 'url': 'https://example.com/ca'}
        admitted = collection_assessment(canada, profile, match(canada, profile, discovery=True))
        self.assertEqual(admitted['collection_decision'], 'admitted')

    def test_collect_filters_deduplicates_and_preserves_output_on_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            config = root / 'sources.json'
            config.write_text(json.dumps({'sources': [{'type': 'greenhouse', 'board': 'example'}]}))
            args = argparse.Namespace(profile=ROOT / 'profile.example.json', sources=config, output=root / 'jobs.csv', cache_dir=root / 'cache', min_score=1)
            job = {'title': 'Python Developer', 'absolute_url': 'https://example.com/1', 'location': {'name': 'Remote - Canada'}, 'content': 'Python SQL'}
            with patch('job_sources.fetch', return_value=({'jobs': [job, job, {**job, 'title': 'Senior Python Developer', 'absolute_url': 'https://example.com/2'}]}, 'today', False)):
                collect(args)
            self.assertEqual(len(read_csv(args.output, ['title'])), 1)
            original = args.output.read_bytes()
            with patch('job_sources.fetch', side_effect=OSError('Unavailable')):
                with self.assertRaisesRegex(ValueError, 'All sources failed'):
                    collect(args)
            self.assertEqual(args.output.read_bytes(), original)

    def test_cache_avoids_network(self):
        with tempfile.TemporaryDirectory() as folder:
            import hashlib
            from job_sources import endpoint
            source = {'type': 'remotive'}
            path = Path(folder) / (hashlib.sha256(endpoint(source).encode()).hexdigest() + '.json')
            path.write_text(json.dumps({'data': {'jobs': []}, 'fetched_at': 'original timestamp'}))
            with patch('job_sources.urlopen', side_effect=AssertionError('Cache should prevent request')):
                data, stamp, cached = fetch(source, Path(folder))
            self.assertTrue(cached)
            self.assertEqual(stamp, 'original timestamp')


if __name__ == '__main__':
    unittest.main()
