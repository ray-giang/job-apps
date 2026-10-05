#!/usr/bin/env python3
"""Select fact-locked resume content for one collected job."""

import argparse
import csv
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent

TRACKS = {
    "management": ("manager", "leadership", "hiring", "roadmap", "stakeholder", "kpi"),
    "marketing": ("marketing", "attribution", "measurement", "incrementality", "campaign", "mmm"),
    "product": ("product", "experimentation", "conversion", "retention", "monetization"),
    "data_science": ("data science", "statistical", "segmentation", "forecasting", "python", "experiment"),
    "analytics_engineering": ("analytics engineer", "data engineer", "dbt", "snowflake", "airflow", "data model", "pipeline"),
}

TRACK_SKILLS = {
    "management": ("Team Leadership", "Hiring", "Performance Management", "Analytics Roadmaps", "Stakeholder Management", "KPI Governance"),
    "marketing": ("Marketing Analytics", "Marketing Attribution", "Experimentation", "A/B Testing", "Statistical Testing", "SQL", "Python"),
    "product": ("Product Analytics", "Experimentation", "A/B Testing", "Statistical Testing", "SQL", "Python", "Data Visualization"),
    "data_science": ("Python", "SQL", "Experimentation", "A/B Testing", "Statistical Testing", "Revenue Forecasting", "Product Analytics"),
    "analytics_engineering": ("SQL", "dbt", "Snowflake", "Airflow", "Python", "Git", "Fivetran", "Looker"),
}


def normalized_words(text):
    return set(re.findall(r"[a-z][a-z0-9+#.-]+", text.lower()))


def choose_track(job):
    title = job.get("title", "").lower()
    if "manager" in title and re.search(r"analytics|data science|insights|measurement", title):
        return "management"
    if re.search(r"analytics engineer|data engineer|bi engineer|business intelligence engineer", title):
        return "analytics_engineering"
    if re.search(r"data scientist|decision scientist|applied scientist", title):
        return "data_science"
    if re.search(r"marketing science|marketing analytics|measurement", title):
        return "marketing"
    if re.search(r"product analyst|product analytics", title):
        return "product"
    text = f"{title} {job.get('department', '')} {job.get('description', '')}".lower()
    scores = {track: sum(text.count(term) for term in terms) for track, terms in TRACKS.items()}
    return max(scores, key=scores.get) if max(scores.values(), default=0) else "general"


def bullet_score(bullet, job_words, track):
    tags = set(bullet.get("tags", []))
    words = normalized_words(bullet["text"])
    overlap = len((tags | words) & job_words)
    track_bonus = 4 if track in tags else 0
    metric_bonus = 2 if re.search(r"(?:\d+%|\$\d|\d+K)", bullet["text"]) else 0
    return overlap + track_bonus + metric_bonus


def select_resume(master, job, max_bullets=14):
    track = choose_track(job)
    job_words = normalized_words(f"{job.get('title', '')} {job.get('department', '')} {job.get('description', '')}")
    roles, selected_ids = [], []
    remaining = max_bullets
    slot_limits = [4, 4, 4, 2, 2, 2]
    for role_index, role in enumerate(master["experience"]):
        ranked = sorted(role["bullets"], key=lambda b: (-bullet_score(b, job_words, track), b["id"]))
        maximum = slot_limits[role_index] if role_index < len(slot_limits) else len(ranked)
        future_minimum = len(master["experience"]) - role_index - 1
        count = min(len(ranked), maximum, max(1, remaining - future_minimum))
        picked = ranked[:count]
        remaining -= len(picked)
        selected_ids.extend(b["id"] for b in picked)
        roles.append({**{k: v for k, v in role.items() if k != "bullets"}, "bullets": picked})
    preferred = TRACK_SKILLS.get(track, ())
    relevant_skills = sorted(master["skills"], key=lambda s: (-(6 if s in preferred else 0) - len(normalized_words(s) & job_words), preferred.index(s) if s in preferred else len(preferred) + master["skills"].index(s)))
    skill_character_budget = 235 if track == "analytics_engineering" else 180
    selected_skills = []
    for skill in relevant_skills:
        candidate = selected_skills + [skill]
        if len("| " + " | ".join(candidate) + " |") <= skill_character_budget:
            selected_skills = candidate
        if len(selected_skills) == 16:
            break
    return {
        "schema_version": 1,
        "target": {"company": job.get("company", ""), "title": job.get("title", ""), "url": job.get("url", "")},
        "track": track,
        "template_source": master.get("template_sources", {}).get(track, master.get("template_sources", {}).get("layout_authority", "")),
        "contact": master["contact"],
        "headline": master["headline_options"].get(track, master["headline_options"]["general"]),
        "summary_facts": master["summary_facts"],
        "skills": selected_skills,
        "experience": roles,
        "education": master["education"],
        "evidence_ids": selected_ids,
        "evidence_library": {bullet["id"]: bullet["text"] for role in master["experience"] for bullet in role["bullets"]},
        "guardrail": "All claims are selected from resume_master.json; no new metrics, employers, dates, titles, or achievements were generated."
    }


def find_job(path, query):
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    matches = [row for row in rows if query.lower() in " ".join((row.get("title", ""), row.get("company", ""), row.get("url", ""))).lower()]
    if len(matches) != 1:
        raise ValueError(f"Expected one job for {query!r}; found {len(matches)}")
    return matches[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", help="Unique title, company/title phrase, or job URL fragment from jobs.csv")
    parser.add_argument("--jobs", type=Path, default=ROOT / "jobs.csv")
    parser.add_argument("--master", type=Path, default=ROOT / "resume_master.json")
    parser.add_argument("--output", type=Path, default=ROOT / "tailored_resumes" / "resume_selection.json")
    parser.add_argument("--max-bullets", type=int, default=18)
    args = parser.parse_args()
    master = json.loads(args.master.read_text(encoding="utf-8"))
    result = select_resume(master, find_job(args.jobs, args.query), args.max_bullets)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Saved fact-locked resume selection for {result['target']['company']} / {result['target']['title']} to {args.output}")


if __name__ == "__main__":
    main()
