# Employer coverage

The active source registry contains public company career feeds that were live and showed Canada or Toronto locations when verified. A company-level feed is useful coverage, not proof that every posting supports Raymond's location, compensation, role, or employment requirements.

## Added September 14, 2026

| Employer | Feed | Fit rationale | Verification snapshot |
| --- | --- | --- | --- |
| AlphaSense | Greenhouse | B2B market-intelligence technology; Canada-remote roles observed | 222 listings |
| Clutch | Greenhouse | Canadian high-growth digital marketplace | 77 listings |
| D2L | Greenhouse | Canadian B2B SaaS | 31 listings |
| StackAdapt | Greenhouse | Toronto-founded advertising technology and analytics | 72 listings |
| Trolley | Greenhouse | B2B payments technology; Canadian high-growth recognition | 14 listings |
| 1Password | Ashby | Canadian B2B security SaaS | 61 listings |
| Float | Ashby | Canadian fintech software | 20 listings |
| Wealthsimple | Ashby | Canadian fintech technology | 56 listings |
| ZayZoon | Ashby | Canadian workplace fintech and high-growth employer | 5 listings |
| Noibu | Ashby | Canadian e-commerce SaaS and high-growth employer | 6 listings |

The verification count is a point-in-time count for the whole global feed. It is not the number of relevant jobs or Canadian openings.

## Considered but not activated

KOHO's Ashby feed worked, but the current feed did not expose a Canada or Toronto location string during automated verification. Intercom's Greenhouse feed worked but did not show Canadian locations. TouchBistro's Greenhouse endpoint returned zero listings. Other tested slugs returned 404 and require platform discovery rather than guessing another slug.

Banks and government employers remain excluded. Neo Financial was not added because the user excludes banks. A company being fintech-adjacent does not waive the job-level location and compensation checks.

## How to expand coverage

1. Add supported Greenhouse or Ashby board slugs to `sources.json` after verifying the endpoint and Canadian hiring footprint.
2. Add adapters for Workday and custom career sites. Lever is now supported. Several attractive Canadian employers use Workday, so company research alone cannot make them collectable today.
3. Recheck inactive employers periodically because platforms, board slugs and geographic hiring change.
4. Use employer suggestions and posting links from the user as seeds. They reveal both missing companies and missing title language.

Research seeds included Deloitte Canada's 2025 Technology Fast 50 and Enterprise Industry Leaders, plus current Canada-remote analytics postings. Employer fit remains a preference signal; it is not yet part of ranking.

## Expansion to 77 configured employers

Twenty-eight employers were added after verifying a working public feed and at least one Canada, Ontario, or Toronto location. Additions include Lookout, AutoTrader Canada, Knak, Scopely, PagerDuty, Mercury, Grafana Labs, Cockroach Labs, League, Cohere, Vanta, Snowflake, Loopio, Fullscript, BioRender, Achievers, Babylist, Behavox, Mozilla, Canonical, Voldex, Wrapbook, Confluent, Directive, Sonatype, Luxury Presence, Caseware and Veeva.

Lever is now a supported source type. Its public feed supplies workplace type, location, commitment, department, team, description and available compensation text. This raised supported platform coverage from two ATS families to three.

The registry now exceeds the 75-employer target. It adds Google, Shopify, Amazon, Microsoft and Uber as must-have first-party career sources; reusable Workday support for ServiceTitan, Autodesk and Thomson Reuters; and patched Ashby coverage for Hopper, Marqeta, Blackpoint Cyber and Hive. Workday results are paginated and enriched from each public detail endpoint. HTML-based sources are optional so a markup change cannot erase healthy results from the other employers.
