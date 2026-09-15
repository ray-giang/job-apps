# Personal job assistant

A small Python script you can run from the VS Code terminal. It collects public job listings, ranks them against your preferences, explains the matches, and tracks applications in a CSV file. Uses Python 3.10 or later with no extra packages.

## Collect real jobs automatically

```sh
python3 job_assistant.py collect
python3 job_assistant.py rank
```

`collect` downloads public job-board feeds from the companies in `sources.json`, converts HTML descriptions into text, filters against your profile, removes duplicate URLs, and writes `jobs.csv`. `rank` then produces `matches.csv` with scores and review notes. No API key or additional Python packages are required for these public feeds. Your resume and profile stay local; only feed requests go to the sources.

There are currently 77 configured employer sources across Greenhouse, Ashby, Lever, Workday, Amazon's public search API, and selected first-party careers pages. See `sources.json` for the full list. Individual jobs still require eligibility review. This is curated coverage, not a search of the entire job market. It includes remote and hybrid listings when those companies publish them. It does not scrape LinkedIn or Indeed. Custom careers pages are marked optional because their HTML changes more often; one optional failure no longer discards results from healthy feeds.

Edit `sources.json` to add company boards. Supported entries look like:

```json
{
  "sources": [
    {"type": "greenhouse", "board": "fivetran", "company": "Fivetran"},
    {"type": "greenhouse", "board": "affirm", "company": "Affirm"}
  ]
}
```

For Greenhouse, the board slug is the company portion of `boards.greenhouse.io/COMPANY` or `job-boards.greenhouse.io/COMPANY`. For Ashby, add `{"type": "ashby", "board": "COMPANY", "company": "Company name"}` using the exact board identifier from `jobs.ashbyhq.com/COMPANY`; spaces and dots are supported and safely encoded. For Lever, use `{"type": "lever", "board": "COMPANY", "company": "Company name"}` with the site name from `jobs.lever.co/COMPANY`. Workday entries use the tenant's public `/wday/cxs/TENANT/SITE/jobs` endpoint. Optional `{"type": "remotive"}` uses Remotive's remote jobs feed and retains source attribution and its listing URL.

Each feed is cached for six hours in `.job_cache/`. Re-running collection within that window re-filters cached listings against your latest preferences. `fetched_at` records the actual retrieval time. A successful collection replaces the previous `jobs.csv`; application tracking stays in its separate file. If all feeds fail, or a partial failure would overwrite an existing output, collection preserves the previous file and reports an error. A first run with partial failures creates a partial result with a warning. Use `--output jobs.partial.csv` if you explicitly want a separate partial result.

### Collection confidence gate

The collector evaluates every normalized posting before it can enter `jobs.csv`. Existing hard rules first reject unrelated titles, temporary work, onsite roles, non-Toronto hybrid roles, Canada-ineligible roles and clearly inadequate disclosed pay. It also rejects physical locations outside Toronto/Canada unless remote eligibility is explicit, and remote regions that do not include Canada.

Surviving postings receive an evidence score out of 100:

| Evidence | Maximum | How it is earned |
| --- | ---: | --- |
| Role | 40 | Direct target title; department-assisted discovery receives 28 |
| Responsibilities | 20 | Both technical and analytical signals in the description; partial evidence receives 10 |
| Location | 15 | Canada eligibility plus remote/Toronto-hybrid work is confirmed |
| Employment | 10 | Permanent, regular or full-time status is explicit; unknown status receives 5 |
| Compensation | 15 | Entire range starts at or above CAD 175K |

Compensation uses a more detailed preference scale: 15 when the entire range meets CAD 175K; 12 when it starts at or above the CAD 160K base floor and reaches CAD 175K; 10 when only the upper portion reaches CAD 175K; 7 when the range reaches CAD 160K but not CAD 175K; and 4 when pay is below the floor, missing or too ambiguous to compare. An extracted ceiling below CAD 160K is still rejected even though its audit score is 4. Unknown compensation remains reviewable so Canadian postings without salary disclosure are not automatically lost.

Salary extraction supports `CAD`, `CAN`, `CA$`, `C$`, Canadian-context dollar ranges, K notation, separate Canada/US ranges, and narrative minimum/midpoint/maximum bands. For Ashby, structured annual CAD compensation tiers take priority over blended display summaries. It preserves the selected source line or structured tier in `salary_evidence` and labels extraction as `exact`, `context`, `ambiguous` or `none`. Multiple Canadian location tiers remain ambiguous rather than choosing a favorable band. Dollar-denominated revenue, budgets and other non-pay figures are not treated as salary evidence.

The default admission threshold is 60. Scores of 80 or more are labeled `high_confidence_match`; lower admitted scores are `review_required`. A generic analyst title cannot enter without analytical responsibility evidence. Explicitly unrelated analyst families such as FP&A, security, benefits, underwriting, ERP support, treasury and internal audit are excluded.

`jobs.csv` contains only admitted postings. `jobs_audit.csv` records both admitted and rejected evaluations, including `collection_decision`, `rejection_reason`, the five component confidence scores, `overall_confidence`, `admission_reasons` and the source evidence. Both files are local and ignored by Git. `manual_review_required` remains true until location/work mode, permanent status and compensation are all confirmed; a high confidence match is not authorization to submit an application.

Pay extraction accepts only one explicitly annual CAD range and preserves source pay text in `salary_raw`. Base versus total cash must be explicit; bonuses are not guessed. Remote eligibility is inferred conservatively from location labels; ambiguous regions stay flagged for review. Unknown fields do not establish that a job meets your requirements. Check original postings for province restrictions, office days, pay tiers, bonus terms, and whether applications remain open. The collector does not interpret every sentence of a job description or guarantee current availability.

The source adapter lives in `job_sources.py`; `sources.json` controls coverage, and `test_job_sources.py` checks normalization, filtering, caching and failure handling.

API references: [Greenhouse Job Board API](https://docs.greenhouse.io/job-board.html), [Ashby Job Postings API](https://developers.ashbyhq.com/docs/public-job-posting-api), [Lever Postings API](https://github.com/lever/postings-api), [Remotive API](https://github.com/remotive-io/remote-jobs-api). Workday and the custom employer adapters use public first-party career endpoints and are covered by local fixture tests. Remotive's public data has a 24-hour delay and its documentation recommends at most four retrievals per day.

## Your configured analytics search

Your local `profile.json` targets manager/senior-manager analytics and data science roles, plus unprefixed, senior, lead, staff and principal IC roles in analytics, analytics engineering, data science and relevant analyst job families. Analyst coverage includes data, product, growth, marketing, revenue operations, business intelligence, insights and business analyst titles. Junior/intern, director/executive and explicitly temporary titles are excluded. These title rules broaden discovery; they do not prove appropriate responsibilities or seniority. Role-priority weighting and detailed domain fit still need implementation. It accepts Canada-eligible remote work (preferred) and Toronto hybrid work. Compensation targets annual **CAD 175,000–200,000 base plus cash bonus**, excluding equity and RRSP matching. A parsed annual CAD base-pay ceiling below CAD 160,000 is now excluded. Missing or unparsed pay remains for review. Above-target jobs remain eligible. Current compensation is saved only as background; it is not used in scoring or sent anywhere.

Run the tailored fictional demo:

```sh
python3 job_assistant.py rank --jobs jobs.analytics.example.csv
```

The personal profile already exists, so edit it instead of running `setup` again. `profile.example.json` remains a generic demonstration.

For salary and workplace checks, add these optional columns to your real `jobs.csv` (see the analytics example):

| Column | Values / meaning |
| --- | --- |
| `work_mode` | `remote`, `hybrid`, `onsite`; blank means unknown |
| `canada_eligible` | `true` only when posting confirms you can work from Toronto; `false` when excluded; otherwise blank |
| `salary_min`, `salary_max` | Numeric annual amounts, e.g. `175000`; a fixed salary can use the same amount twice |
| `salary_currency` | Explicit currency, e.g. `CAD` or `USD`; do not infer from `$` |
| `salary_period` | `annual` for comparison; other periods flagged for review |
| `salary_basis` | `base` or `total_cash` (base plus cash bonus); equity-inclusive compensation is not comparable |

Record the advertised compensation basis faithfully. Include a target bonus in total cash only when stated; a target bonus is not guaranteed income. Preserve extra fields such as `bonus_notes`, `rrsp_match_percent`, `equity_notes` and `office_days` in your input: they are carried through to the report, but not scored or converted.

The tailored score allocates 45 points to title/track fit, up to 25 to skill keyword coverage, 10 to confirmed eligible remote work (5 for Toronto hybrid), and up to 20 to comparable salary. Roles outside the title patterns, explicitly ineligible Canadian hiring, onsite work, hybrid outside Toronto, and confirmed total cash ceilings below CAD 175k are excluded. A range that only partly reaches CAD 175k stays visible with a review note. Missing pay, unknown location eligibility, USD pay, and base-only ranges that require bonus information remain visible with review notes and no points for that uncertain criterion.

These are transparent keyword and structured-field checks, not a semantic resume assessment or automatic interpretation of a job's legal eligibility. Check the original posting. Role patterns are editable. General software engineering and director roles are outside the title patterns; data science titles can include ML/research work and need responsibility review. Background experience is context rather than a hard years-of-experience filter.

## Start in VS Code

Open this folder in VS Code, then open **Terminal → New Terminal**.

Try the fictional sample listings first:

```sh
python3 job_assistant.py rank --profile profile.example.json --jobs jobs.example.csv
```

On Windows, use `py` instead of `python3` if needed.

Create your own profile:

```sh
python3 job_assistant.py setup
```

Edit `profile.json` anytime to change your roles, skills, locations, remote preference, or excluded keywords. Add title variants as separate roles, for example `Software Developer` and `Software Engineer`.

## Add real listings

The `collect` command creates `jobs.csv` automatically. You can also create it manually using the same columns as `jobs.example.csv`:

- `title`, `company`, `location`, `remote`, `description`, `url`
- Set `remote` to `true` or `false` explicitly.
- Quote descriptions containing commas, as in the example.

Paste listings you find or import a compatible CSV export, then run:

```sh
python3 job_assistant.py rank
```

The terminal shows the top ten matches; `matches.csv` contains all matches with a positive score. Use `--min-score 50` to narrow the results. Running again replaces the previous matches report.

For the generic example profile, title matches contribute 60 points, your matched skills up to 30, and a preferred location 10; weights are normalized when preferences are omitted. Generic locations are preferences, not hard filters. Remote-only and excluded keywords are hard filters. Exclusions apply anywhere in the title, location, or description. Your tailored profile uses the rules above and leaves broad exclusions empty so mentions of senior colleagues do not remove relevant jobs.

## Track applications

Save a listing:

```sh
python3 job_assistant.py track --url "https://example.com/jobs/1" --company "Example" --title "Python Developer"
```

After applying, update the same URL:

```sh
python3 job_assistant.py track --url "https://example.com/jobs/1" --status applied --notes "Applied through company website"
```

Available statuses: `saved`, `applied`, `interview`, `offer`, `rejected`, `withdrawn`. Records are stored in `applications.csv`. Reusing a URL updates the existing record and preserves notes unless new notes are provided.

The script fetches configured public feeds and works with local files. It does not generate cover letters or submit applications. The example jobs and URLs are fictional. Your personal input and output files are excluded from Git by default.

Run behavior checks with `python3 -m unittest -v`.

New preferences for permanent employment, maximum three hybrid days, commute and timezone remain saved but are not fully enforced. Title exclusions remove explicitly temporary roles; missing employment type is not proof of permanence. Source coverage is curated; new employers are not discovered automatically. Run `python3 -m unittest -q` for source, title and matching checks.

IC title coverage also includes any analyst title, Analytics Lead, Data Engineer, Business Intelligence Engineer and BI Engineer, with or without seniority prefixes. Generic analyst titles can include unrelated work; the title match is a discovery signal, not confirmation of role fit.

## Department-assisted discovery

`collect` now preserves Greenhouse department names and Ashby department/team names. Your `department_discovery` profile setting enables a fallback for ambiguous titles such as “Manager, Insights” or “Decision Scientist”. It requires a relevant department/team or department phrase in the title, an appropriate role indicator, and both a technical and an analytical signal in the description. Department membership alone is insufficient. Existing title exclusions, workplace and salary checks still apply. This is a keyword heuristic, not semantic verification of duties.

`jobs.csv` includes `department`, `team`, `discovery_method`, `discovery_evidence` and `review_notes`. Filter `discovery_method` to `department_and_description` to see newly admitted roles. Remotive's board category is not treated as an employer department.

This change affects discovery only: `rank` still uses the existing title gate and score, so department-only candidates stay in `jobs.csv` for review and do not yet enter `matches.csv`. Existing title matches keep the same scores. Department-priority ranking is not implemented.
