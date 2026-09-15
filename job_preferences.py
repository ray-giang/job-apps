"""Optional role, workplace and compensation checks for structured listings."""

import math
import re


def number(value):
    if value is None or str(value).strip() == "":
        return None
    result = float(str(value).replace(",", "").strip())
    if not math.isfinite(result) or result < 0:
        raise ValueError("Amounts must be finite nonnegative numbers.")
    return result


def normalize(value):
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def role_matches(title, profile):
    normalized = normalize(title)
    if any(re.search(pattern, normalized) for pattern in profile.get("exclude_title_patterns", [])):
        return []
    return [track["name"] for track in profile.get("role_tracks", [])
            if any(re.search(pattern, normalized) for pattern in track["patterns"])]


def department_discovery(job, profile):
    """Evidence for discovery only; never award department ranking points."""
    settings = profile.get("department_discovery", {})
    if not settings.get("enabled", False):
        return ""
    title = normalize(job.get("title", ""))
    if any(re.search(p, title) for p in profile.get("exclude_title_patterns", [])):
        return ""
    if re.search(r"\b(?:engineer|product manager|program manager|project manager|account manager|sales manager|designer|recruiter)\b", title):
        return ""
    if not re.search(r"\b(?:insights?|decision scien(?:ce|tist)|analytics|analyst|manager|scientist)\b", title):
        return ""
    evidence = []
    for field in ("department", "team", "title"):
        value = job.get(field, "")
        normalized = normalize(value)
        if any(re.search(r"\b" + re.escape(normalize(term)) + r"\b", normalized)
               for term in settings.get("terms", [])):
            evidence.append(f"{field}: {value}")
    if not evidence:
        return ""
    description = normalize(job.get("description", ""))
    technical = re.search(r"\b(?:sql|python|dbt|snowflake|looker|tableau|power bi)\b", description)
    analytical = re.search(r"\b(?:experimentation|a b test(?:ing|s)?|statistical analysis|product analytics|marketing analytics|forecasting|attribution|data model(?:ing|s)?|data analysis|business intelligence)\b", description)
    if not technical or not analytical:
        return ""
    return "; ".join(evidence + [f"Description signals: {technical.group()}, {analytical.group()}"])


def workplace(job, profile):
    """Return (eligible, points, review notes); unknown eligibility stays visible."""
    rules = profile.get("work_preferences")
    if not rules:
        return True, 0, []
    mode = job.get("work_mode", "").strip().lower()
    if not mode and job.get("remote", "").strip().lower() in {"true", "yes", "1"}:
        mode = "remote"
    if mode == "onsite":
        return False, 0, []
    eligible = job.get("canada_eligible", "").strip().lower()
    if eligible in {"false", "no", "0"}:
        return False, 0, []
    if mode == "remote":
        if eligible in {"true", "yes", "1"}:
            return True, 10, []
        return True, 0, ["Verify remote hiring eligibility from Toronto, Canada"]
    if mode == "hybrid":
        location = normalize(job.get("location", ""))
        allowed = rules.get("hybrid_locations", [])
        if any(re.search(r"\b" + re.escape(normalize(place)) + r"\b", location) for place in allowed):
            return True, 5, ["Confirm office address and required hybrid days"]
        if location:
            return False, 0, []
        return True, 0, ["Verify hybrid office is in Toronto"]
    return True, 0, ["Verify work mode: remote or Toronto hybrid required"]


def compensation(job, profile):
    """Compare annual cash on the same basis only; do not infer FX or bonuses."""
    target = profile.get("compensation")
    if not target:
        return True, 0, "not_configured", []
    try:
        low = number(job.get("salary_min"))
        high = number(job.get("salary_max"))
        if low is not None and high is not None and low > high:
            raise ValueError("Salary minimum exceeds maximum")
    except (ValueError, TypeError):
        return True, 0, "review", ["Invalid salary range; verify original posting"]
    if low is None and high is None:
        if job.get("salary_raw", "").strip():
            return True, 0, "review", ["Pay text available in salary_raw; verify currency, annual range and bonus"]
        return True, 0, "undisclosed", ["Compensation undisclosed"]
    currency = job.get("salary_currency", "").strip().upper()
    period = job.get("salary_period", "").strip().lower()
    basis = job.get("salary_basis", "").strip().lower()
    if currency != target["currency"] or period != "annual":
        return True, 0, "review", ["Verify annual CAD pay; no currency or period conversion applied"]
    if basis == "base" and high is not None and high < target.get("minimum_base_cad", 0):
        return False, 0, "below_base_minimum", []
    if basis != target["basis"]:
        # A base floor already above the cash target is sufficient; a low base
        # ceiling cannot exclude total cash without knowing the bonus.
        if target["basis"] == "total_cash" and basis == "base" and low is not None and low >= target["min"]:
            return True, 20, "base_meets_cash_target", ["Base alone meets cash minimum; confirm bonus"]
        return True, 0, "review", [f"Need {target['basis']} range; listing basis is {basis or 'unknown'}"]
    if high is not None and high < target["min"]:
        return False, 0, "below_target", []
    if low is not None and low >= target["min"]:
        status = "above_target" if low > target["max"] else "meets_target"
        return True, 20, status, []
    if high is not None and high >= target["min"]:
        return True, 10, "partly_meets_target", ["Only part of the advertised range meets your minimum"]
    return True, 0, "review", ["Salary ceiling unknown; confirm whether target is achievable"]


def validate_preferences(profile):
    discovery = profile.get("department_discovery", {})
    if not isinstance(discovery, dict) or not isinstance(discovery.get("enabled", False), bool):
        raise ValueError("department_discovery must be an object with boolean enabled")
    terms = discovery.get("terms", [])
    if not isinstance(terms, list) or not all(isinstance(v, str) and normalize(v) for v in terms):
        raise ValueError("department_discovery terms must be a list of nonempty department names")
    exclusions = profile.get("exclude_title_patterns", [])
    if not isinstance(exclusions, list) or not all(isinstance(p, str) and p for p in exclusions):
        raise ValueError("exclude_title_patterns must be a list of nonempty patterns")
    for pattern in exclusions:
        try:
            re.compile(pattern)
        except re.error as error:
            raise ValueError(f"Invalid title exclusion: {error}") from error
    tracks = profile.get("role_tracks", [])
    if not isinstance(tracks, list):
        raise ValueError("role_tracks must be a list")
    for track in tracks:
        if not isinstance(track, dict) or not isinstance(track.get("name"), str) or not track["name"]:
            raise ValueError("Each role track needs a name")
        patterns = track.get("patterns")
        if not isinstance(patterns, list) or not patterns or not all(isinstance(p, str) and p for p in patterns):
            raise ValueError("Each role track needs a nonempty patterns list")
        for pattern in patterns:
            try:
                re.compile(pattern)
            except re.error as error:
                raise ValueError(f"Invalid role pattern: {error}") from error
    work = profile.get("work_preferences")
    if work is not None:
        if not isinstance(work, dict) or not isinstance(work.get("hybrid_locations"), list) or not all(isinstance(v, str) and v.strip() for v in work["hybrid_locations"]):
            raise ValueError("work_preferences needs a hybrid_locations list")
    target = profile.get("compensation")
    if target is not None:
        if not isinstance(target, dict) or target.get("basis") not in {"base", "total_cash"} or target.get("currency") != "CAD":
            raise ValueError("compensation needs CAD currency and base or total_cash basis")
        for key in ("min", "max"):
            if isinstance(target.get(key), bool) or not isinstance(target.get(key), (int, float)) or number(target[key]) is None:
                raise ValueError("compensation min and max must be numbers")
        if target["min"] > target["max"]:
            raise ValueError("compensation min must not exceed max")
