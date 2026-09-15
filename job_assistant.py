"""Personal job matching and application tracking. Python 3.10+, no dependencies."""

import argparse
import csv
import json
import re
from datetime import date
from pathlib import Path

from job_preferences import compensation, department_discovery, role_matches, validate_preferences, workplace

ROOT = Path(__file__).resolve().parent
TRACKER_FIELDS = ["company", "title", "url", "status", "updated", "notes"]


def terms(value):
    return [item.strip() for item in value.split(",") if item.strip()]


def contains(text, phrase):
    return bool(re.search(r"(?<!\w)" + re.escape(phrase.strip()) + r"(?!\w)", text, re.I))


def setup(path):
    if path.exists():
        raise ValueError(f"{path} already exists. Edit it directly, or choose --profile another.json.")
    profile = {
        "roles": terms(input("Target roles, comma separated: ")),
        "skills": terms(input("Your skills, comma separated: ")),
        "locations": terms(input("Preferred locations (blank = any): ")),
        "remote_only": input("Remote only? [y/N]: ").strip().lower() in {"y", "yes"},
        "exclude_keywords": terms(input("Exclude jobs mentioning (e.g. senior, unpaid): ")),
    }
    path.write_text(json.dumps(profile, indent=2) + "\n", encoding="utf-8")
    print(f"Saved {path}")


def load_profile(path):
    profile = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(profile, dict):
        raise ValueError("Profile must be a JSON object.")
    for key in ("roles", "skills", "locations", "exclude_keywords"):
        values = profile.get(key, [])
        if not isinstance(values, list) or not all(isinstance(v, str) and v.strip() for v in values):
            raise ValueError(f"Profile '{key}' must be a list of nonempty strings.")
    if not isinstance(profile.get("remote_only", False), bool):
        raise ValueError("Profile 'remote_only' must be true or false.")
    if not profile.get("roles") and not profile.get("skills"):
        raise ValueError("Add at least one target role or skill to your profile.")
    validate_preferences(profile)
    return profile


def read_csv(path, required):
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not set(required).issubset(reader.fieldnames or []):
            raise ValueError(f"{path} needs columns: {', '.join(required)}")
        return [{key: value or "" for key, value in row.items() if key} for row in reader]


def write_csv(path, fields, rows):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def match(job, profile, *, discovery=False):
    """Return an explainable keyword score, or None for a hard exclusion."""
    text = " ".join(job.get(field, "") for field in ("title", "location", "description"))
    if any(contains(text, word) for word in profile.get("exclude_keywords", [])):
        return None
    if profile.get("remote_only") and job.get("remote", "").strip().lower() not in {"true", "yes", "1"}:
        return None
    roles = [role for role in profile.get("roles", []) if contains(job["title"], role)]
    department_evidence = ""
    if profile.get("role_tracks"):
        roles = role_matches(job["title"], profile)
        if not roles:
            department_evidence = department_discovery(job, profile) if discovery else ""
            if not department_evidence:
                return None
    work_ok, work_points, work_notes = workplace(job, profile)
    pay_ok, pay_points, pay_status, pay_notes = compensation(job, profile)
    if not work_ok or not pay_ok:
        return None
    skills = [skill for skill in profile.get("skills", []) if contains(text, skill)]
    locations = [place for place in profile.get("locations", []) if contains(job.get("location", ""), place)]
    weights = {"roles": 60, "skills": 30, "locations": 10}
    available = sum(weight for key, weight in weights.items() if profile.get(key))
    earned = (60 if roles else 0) + (30 * len(skills) / len(profile["skills"]) if profile.get("skills") else 0) + (10 if locations else 0)
    reasons = []
    for label, values in (("Role", roles), ("Skills", skills), ("Location", locations)):
        if values:
            reasons.append(f"{label}: {', '.join(values)}")
    if profile.get("work_preferences") or profile.get("compensation"):
        # Senior track fit dominates; remote and comparable pay improve ranking.
        available = (45 if profile.get("roles") or profile.get("role_tracks") else 0) + (25 if profile.get("skills") else 0) + (10 if profile.get("work_preferences") else 0) + (20 if profile.get("compensation") else 0)
        earned = (45 if roles else 0) + (25 * len(skills) / len(profile["skills"]) if profile.get("skills") else 0) + work_points + pay_points
    review_notes = work_notes + pay_notes
    if department_evidence:
        review_notes.append("Department-assisted discovery only; role fit needs review before ranking")
    return {**job, "score": round(100 * earned / available) if available else 0,
            "discovery_method": "department_and_description" if department_evidence else "title",
            "discovery_evidence": department_evidence or "; ".join(roles),
            "compensation_status": pay_status,
            "review_notes": "; ".join(review_notes),
            "match_reasons": "; ".join(reasons) or "No keyword matches"}


def rank(args):
    profile = load_profile(args.profile)
    jobs = read_csv(args.jobs, ["title", "company", "location", "remote", "description", "url"])
    ranked, seen = [], set()
    for job in jobs:
        key = job["url"].strip() or (job["company"].casefold(), job["title"].casefold(), job["location"].casefold())
        if key in seen:
            continue
        seen.add(key)
        result = match(job, profile)
        if result is not None and result["score"] >= args.min_score:
            ranked.append(result)
    ranked.sort(key=lambda job: job["score"], reverse=True)
    fields = ["score", "title", "company", "location", "remote", "url", "match_reasons", "compensation_status", "review_notes", "description"]
    fields += sorted({key for job in jobs for key in job} - set(fields))
    if args.output.resolve() in {args.jobs.resolve(), args.profile.resolve()}:
        raise ValueError("Output must be different from the jobs and profile files.")
    write_csv(args.output, fields, ranked)
    for job in ranked[:10]:
        print(f"{job['score']:3}/100  {job['title']} — {job['company']} ({job['location']})")
        print(f"         {job['match_reasons']}")
        if profile.get("compensation"):
            print(f"         Pay: {job['compensation_status']}")
        if job["review_notes"]:
            print(f"         Review: {job['review_notes']}")
        if job["url"]:
            print(f"         {job['url']}")
    print(f"\nSaved {len(ranked)} matches to {args.output}")


def track(args):
    rows = read_csv(args.tracker, TRACKER_FIELDS) if args.tracker.exists() else []
    row = next((row for row in rows if row["url"] == args.url), None)
    if row is None:
        if not args.company or not args.title:
            raise ValueError("New applications need --company and --title.")
        row = dict.fromkeys(TRACKER_FIELDS, "")
        row["url"] = args.url
        rows.append(row)
    for field in ("company", "title", "notes"):
        if getattr(args, field) is not None:
            row[field] = getattr(args, field)
    row.update(status=args.status, updated=date.today().isoformat())
    write_csv(args.tracker, TRACKER_FIELDS, rows)
    print(f"Saved {row['company']} / {row['title']}: {row['status']} to {args.tracker}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    from job_sources import collect
    collecting = commands.add_parser("collect", help="Fetch public job feeds and build jobs.csv for your profile")
    collecting.add_argument("--profile", type=Path, default=ROOT / "profile.json")
    collecting.add_argument("--sources", type=Path, default=ROOT / "sources.json")
    collecting.add_argument("--output", type=Path, default=ROOT / "jobs.csv")
    collecting.add_argument("--cache-dir", type=Path, default=ROOT / ".job_cache")
    collecting.add_argument("--min-score", type=int, choices=range(101), metavar="0-100", default=1)
    collecting.set_defaults(run=collect)
    create = commands.add_parser("setup", help="Create your matching profile interactively")
    create.add_argument("--profile", type=Path, default=ROOT / "profile.json")
    create.set_defaults(run=lambda args: setup(args.profile))
    ranking = commands.add_parser("rank", help="Rank job listings from a CSV file")
    ranking.add_argument("--profile", type=Path, default=ROOT / "profile.json")
    ranking.add_argument("--jobs", type=Path, default=ROOT / "jobs.csv")
    ranking.add_argument("--output", type=Path, default=ROOT / "matches.csv")
    ranking.add_argument("--min-score", type=int, choices=range(101), metavar="0-100", default=1)
    ranking.set_defaults(run=rank)
    tracking = commands.add_parser("track", help="Record or update an application by its job URL")
    tracking.add_argument("--tracker", type=Path, default=ROOT / "applications.csv")
    tracking.add_argument("--url", required=True)
    tracking.add_argument("--company")
    tracking.add_argument("--title")
    tracking.add_argument("--notes")
    tracking.add_argument("--status", choices=["saved", "applied", "interview", "offer", "rejected", "withdrawn"], default="saved")
    tracking.set_defaults(run=track)
    args = parser.parse_args()
    try:
        args.run(args)
    except (OSError, ValueError, csv.Error) as error:
        parser.exit(1, f"Error: {error}\n")


if __name__ == "__main__":
    main()
