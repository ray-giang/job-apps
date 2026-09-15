"""Collect public job-board feeds using only the Python standard library."""

import hashlib
import html
import json
import re
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, urljoin, urlparse
from urllib.request import Request, urlopen

FIELDS = ["title", "company", "location", "remote", "description", "url", "work_mode",
          "canada_eligible", "salary_min", "salary_max", "salary_currency", "salary_period",
          "salary_basis", "salary_raw", "salary_evidence", "salary_extraction_confidence", "source", "source_id", "published_at", "fetched_at",
          "location_evidence", "extraction_notes", "department", "team", "discovery_method", "discovery_evidence", "review_notes",
          "role_confidence", "responsibility_confidence", "location_confidence", "employment_confidence",
          "compensation_confidence", "compensation_status", "compensation_interpretation", "overall_confidence", "application_readiness", "manual_review_required", "admission_reasons"]

AUDIT_FIELDS = FIELDS + ["collection_decision", "rejection_reason"]


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        if tag in {"p", "div", "li", "br", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)
        if tag in {"p", "div", "li"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def plain(value):
    parser = PlainText()
    parser.feed(html.unescape(value or ""))
    return "\n".join(" ".join(line.split()) for line in "".join(parser.parts).splitlines() if line.strip())


def endpoint(source):
    kind = source.get("type")
    if kind == "remotive":
        return "https://remotive.com/api/remote-jobs"
    if kind in {"workday", "amazon", "careers_html"}:
        url = source.get("url", "")
        if urlparse(url).scheme != "https":
            raise ValueError(f"{kind} sources need an https URL")
        return url
    board = source.get("board", "")
    allowed = r"[A-Za-z0-9._ -]+" if kind == "ashby" else r"[A-Za-z0-9_-]+"
    if not isinstance(board, str) or not re.fullmatch(allowed, board):
        raise ValueError("Company sources need a valid board slug")
    if kind == "greenhouse":
        return f"https://boards-api.greenhouse.io/v1/boards/{quote(board)}/jobs?content=true"
    if kind == "ashby":
        return f"https://api.ashbyhq.com/posting-api/job-board/{quote(board, safe='')}?includeCompensation=true"
    if kind == "lever":
        instance = source.get("instance", "global")
        if instance not in {"global", "eu"}:
            raise ValueError("Lever instance must be global or eu")
        host = "api.lever.co" if instance == "global" else "api.eu.lever.co"
        return f"https://{host}/v0/postings/{quote(board)}?mode=json"
    raise ValueError(f"Unsupported source type: {kind}")


def read_json(request):
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def read_text(url):
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 PersonalJobAssistant/1.0"})
    with urlopen(request, timeout=30) as response:
        return response.read().decode(response.headers.get_content_charset() or "utf-8", "replace")


def fetch_workday(source):
    # Workday CXS rejects page sizes above 20 on many tenants.
    jobs, offset, limit = [], 0, 20
    while True:
        payload = json.dumps({"appliedFacets": {}, "limit": limit, "offset": offset, "searchText": source.get("query", "")}).encode()
        request = Request(source["url"], data=payload, method="POST",
                          headers={"User-Agent": "PersonalJobAssistant/1.0", "Accept": "application/json", "Content-Type": "application/json"})
        page = read_json(request)
        batch = page.get("jobPostings") or []
        if not isinstance(batch, list):
            raise ValueError("Unexpected Workday response")
        for summary in batch:
            path = summary.get("externalPath", "")
            detail_url = source["url"].removesuffix("/jobs") + path
            detail = read_json(Request(detail_url, headers={"User-Agent": "PersonalJobAssistant/1.0", "Accept": "application/json"})) if path else {}
            info = detail.get("jobPostingInfo") or {}
            jobs.append({**summary, **info, "externalPath": path, "jobUrl": info.get("externalUrl") or detail_url})
        offset += len(batch)
        if not batch or offset >= page.get("total", offset):
            break
    return {"jobs": jobs}


def fetch_amazon(source):
    jobs, offset = [], 0
    limit = min(100, int(source.get("max_results", 500)))
    while True:
        separator = "&" if "?" in source["url"] else "?"
        url = f"{source['url']}{separator}offset={offset}&result_limit={limit}"
        page = read_json(Request(url, headers={"User-Agent": "PersonalJobAssistant/1.0", "Accept": "application/json"}))
        batch = page.get("jobs") or []
        jobs.extend(batch)
        offset += len(batch)
        if not batch or offset >= min(int(page.get("hits", offset)), int(source.get("max_results", 500))):
            break
    return {"jobs": jobs}


def fetch_careers_html(source):
    document = read_text(source["url"])
    pattern = source.get("link_pattern", r"/[^\"'<> ]*jobs?[^\"'<> ]+")
    links = []
    for match in re.findall(pattern, html.unescape(document), re.I):
        value = match[0] if isinstance(match, tuple) else match
        url = urljoin(source.get("link_base", source["url"]), value.replace("&amp;", "&"))
        if urlparse(url).netloc == urlparse(source["url"]).netloc and url not in links:
            links.append(url)
    jobs = []
    for url in links[:int(source.get("max_results", 100))]:
        try:
            page = read_text(url)
        except OSError:
            continue
        title_match = (re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)', page, re.I) or
                       re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:title["\']', page, re.I) or
                       re.search(r"<title[^>]*>(.*?)</title>", page, re.I | re.S) or
                       re.search(r"<h1[^>]*>(.*?)</h1>", page, re.I | re.S))
        if title_match:
            title = re.sub(r"\s+[—|-]\s+[^—|]+(?:Careers|Jobs)\s*$", "", plain(title_match.group(1)), flags=re.I)
            jobs.append({"id": url.rsplit("/", 1)[-1].split("?", 1)[0], "title": title,
                         "location": plain(page)[:5000], "description": plain(page), "jobUrl": url})
    return {"jobs": jobs}


def fetch(source, cache_dir):
    url = endpoint(source)
    cache = cache_dir / (hashlib.sha256(url.encode()).hexdigest() + ".json")
    # Remotive advises no more than four retrievals per day. All feeds use a
    # six-hour cache, including empty results. Failed fetches never replace it.
    if cache.exists() and 0 <= time.time() - cache.stat().st_mtime < 21600:
        record = json.loads(cache.read_text(encoding="utf-8"))
        return record["data"], record["fetched_at"], True
    kind = source.get("type")
    if kind == "workday":
        data = fetch_workday(source)
    elif kind == "amazon":
        data = fetch_amazon(source)
    elif kind == "careers_html":
        data = fetch_careers_html(source)
    else:
        request = Request(url, headers={"User-Agent": "PersonalJobAssistant/1.0", "Accept": "application/json"})
        data = read_json(request)
    if isinstance(data, list) and source.get("type") == "lever":
        data = {"jobs": data}
    if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
        raise ValueError("Unexpected feed format: expected a jobs list")
    fetched_at = datetime.now(timezone.utc).isoformat()
    cache_dir.mkdir(parents=True, exist_ok=True)
    temp = cache.with_suffix(".tmp")
    temp.write_text(json.dumps({"data": data, "fetched_at": fetched_at}), encoding="utf-8")
    temp.replace(cache)
    return data, fetched_at, False


def location_fields(location, explicit_mode=""):
    text = location.lower().strip()
    mode = explicit_mode.lower().replace("on-site", "onsite")
    if mode not in {"remote", "hybrid", "onsite"}:
        mode = "hybrid" if "hybrid" in text else "remote" if "remote" in text else "onsite" if re.search(r"on[- ]site", text) else ""
    # Do not use generic mentions of Canada elsewhere in the description.
    # Only unambiguous eligibility labels qualify automatically.
    eligibility = ""
    cleaned = re.sub(r"\bremote\b|[()\-]", " ", text)
    cleaned = " ".join(cleaned.split())
    if re.search(r"\btoronto\b", text) or cleaned in {"canada", "worldwide", "anywhere", "global", "ontario, canada", "canada, ontario"}:
        eligibility = "true"
    elif cleaned in {"united states", "us", "usa", "united states only", "us only", "uk", "united kingdom", "europe", "emea", "india", "australia"}:
        eligibility = "false"
    return {"work_mode": mode, "remote": "true" if mode == "remote" else "false" if mode else "",
            "canada_eligible": eligibility, "location_evidence": location}


def salary_fields(raw):
    """Extract one unambiguous annual Canadian salary range from real posting formats."""
    result = {"salary_raw": raw, "salary_min": "", "salary_max": "", "salary_currency": "", "salary_period": "",
              "salary_basis": "", "salary_evidence": "", "salary_extraction_confidence": "none"}
    amount = r"(?:\d{1,3}(?:,\d{3})+|\d{2,6})(?:\.\d+)?\s*[kK]?"
    currency = r"(?:CAD|CAN|CA\$|C\$|\$)"
    pattern = re.compile(r"(?P<cur1>" + currency + r")?\s*(?P<low>" + amount + r")\s*(?:CAD|CAN)?\s*(?:-|–|—|to|and)\s*(?P<cur2>" + currency + r")?\s*(?P<high>" + amount + r")\s*(?P<after>CAD|CAN)?", re.I)
    candidates = []
    for line in (line.strip() for line in raw.splitlines() if line.strip()):
        for match in pattern.finditer(line):
            before = line[:match.start()]
            explicit = " ".join(filter(None, (match.group("cur1"), match.group("cur2"), match.group("after"))))
            last_canada = max((before.lower().rfind(term) for term in ("canada", "canadian", "cad", "can base")), default=-1)
            last_us = max((before.lower().rfind(term) for term in ("united states", "usa", "usd", "us-based", "us based")), default=-1)
            explicit_cad = bool(re.search(r"\b(?:CAD|CAN)\b|CA\$|C\$", explicit, re.I))
            is_cad = explicit_cad or last_canada > last_us
            is_usd = bool(re.search(r"\bUSD\b|US\$", explicit, re.I)) or (not explicit_cad and last_us > last_canada)
            annual_words = bool(re.search(r"annual|annum|year|base (?:pay|salary)|salary range|compensation", line, re.I))
            k_notation = bool(re.search(r"[\d.]\s*[kK]\b", match.group(0)))
            values_are_annual_scale = all(float(match.group(name).replace(",", "").replace(" ", "").lower().rstrip("k")) *
                                          (1000 if match.group(name).strip().lower().endswith("k") else 1) >= 10000
                                          for name in ("low", "high"))
            if not is_cad or is_usd or not (annual_words or k_notation or (explicit_cad and values_are_annual_scale)):
                continue
            candidates.append((match, line, "exact" if re.search(r"\b(?:CAD|CAN)\b|CA\$|C\$", explicit, re.I) else "context"))
    distinct = {}
    for match, line, confidence in candidates:
        distinct.setdefault((match.group("low"), match.group("high")), (match, line, confidence))
    if len(distinct) != 1:
        result["salary_extraction_confidence"] = "ambiguous" if distinct else "none"
        return result
    match, line, confidence = next(iter(distinct.values()))
    def convert(value):
        value = value.replace(",", "").replace(" ", "").lower()
        return float(value.rstrip("k")) * (1000 if value.endswith("k") else 1)
    low, high = (convert(match.group(name)) for name in ("low", "high"))
    if not 10000 <= low <= high <= 2000000:
        return result
    basis_context = raw if len(distinct) == 1 else line
    basis = "total_cash" if re.search(r"total cash|on.target compensation|\bOTE\b", basis_context, re.I) else "base" if re.search(r"base salary|base pay|starting base", basis_context, re.I) else ""
    result.update(salary_min=low, salary_max=high, salary_currency="CAD", salary_period="annual", salary_basis=basis,
                  salary_evidence=line, salary_extraction_confidence=confidence)
    return result


def normalize_job(item, source, fetched_at):
    kind = source["type"]
    if kind == "ashby" and item.get("isListed") is False:
        return None
    if kind == "remotive":
        title, company = item.get("title", ""), item.get("company_name", "")
        location, mode = item.get("candidate_required_location", ""), "remote"
        description, url = plain(item.get("description")), item.get("url", "")
        raw_pay, published = item.get("salary", ""), item.get("publication_date", "")
    elif kind == "greenhouse":
        title, company = item.get("title", ""), source.get("company", source["board"])
        location, mode = (item.get("location") or {}).get("name", ""), ""
        description, url = plain(item.get("content")), item.get("absolute_url", "")
        raw_pay, published = "", item.get("updated_at", "")
    elif kind == "ashby":
        title, company = item.get("title", ""), source.get("company", source["board"])
        locations = [item.get("location", "")] + [loc.get("location", "") for loc in item.get("secondaryLocations", [])]
        location = "; ".join(filter(None, locations))
        mode = item.get("workplaceType", "") or ("remote" if item.get("isRemote") is True else "")
        description, url = plain(item.get("descriptionHtml") or item.get("descriptionPlain")), item.get("jobUrl", "")
        pay = item.get("compensation") or {}
        raw_pay = pay.get("scrapeableCompensationSalarySummary") or pay.get("compensationTierSummary") or ""
        published = item.get("publishedAt", "")
    elif kind == "lever":
        categories = item.get("categories") or {}
        title, company = item.get("text", ""), source.get("company", source["board"])
        locations = categories.get("allLocations") or [categories.get("location", "")]
        location = "; ".join(str(value) for value in locations if value)
        mode = item.get("workplaceType", "")
        lists = item.get("lists") or []
        description = plain("\n".join(filter(None, [item.get("descriptionPlain", ""), item.get("description", ""),
                                                    *[part.get("content", "") for part in lists if isinstance(part, dict)],
                                                    item.get("additionalPlain", ""), item.get("additional", "")])))
        url = item.get("hostedUrl") or item.get("applyUrl", "")
        salary = item.get("salaryRange") or {}
        raw_pay = item.get("salaryDescriptionPlain") or item.get("salaryDescription") or ""
        if not raw_pay and salary:
            raw_pay = f"{salary.get('currency', '')} {salary.get('min', '')} - {salary.get('max', '')} {salary.get('interval', '')}"
        published = item.get("createdAt", "")
    elif kind == "workday":
        title, company = item.get("title", ""), source.get("company", "")
        location = item.get("location") or "; ".join(item.get("additionalLocations") or [])
        mode = "remote" if "remote" in location.lower() else ""
        description, url = plain(item.get("jobDescription", "")), item.get("jobUrl", "")
        raw_pay, published = "", item.get("startDate", "") or item.get("postedOn", "")
    elif kind == "amazon":
        title, company = item.get("title", ""), source.get("company", "Amazon")
        location, mode = item.get("location", ""), "remote" if "remote" in item.get("location", "").lower() else ""
        description = plain("\n".join(str(item.get(key, "")) for key in ("description", "basic_qualifications", "preferred_qualifications")))
        path = item.get("job_path", "")
        url = urljoin("https://www.amazon.jobs", path)
        raw_pay, published = "", item.get("posted_date", "")
    else:
        title, company = item.get("title", ""), source.get("company", "")
        location, mode = item.get("location", ""), "remote" if "remote" in item.get("location", "").lower() else ""
        description, url = item.get("description", ""), item.get("jobUrl", "")
        raw_pay, published = "", ""
    if not title or not url or urlparse(url).scheme not in {"http", "https"}:
        return None
    if not raw_pay:
        raw_pay = "\n".join(line for line in description.splitlines() if re.search(r"\bCAD\b|\bUSD\b|salary|compensation|\$\s*\d", line, re.I))
    row = dict.fromkeys(FIELDS, "")
    if kind == "greenhouse":
        row["department"] = "; ".join(part["name"] for part in (item.get("departments") or [])
                                        if isinstance(part, dict) and isinstance(part.get("name"), str))
    elif kind == "ashby":
        row["department"] = item.get("department") or ""
        row["team"] = item.get("team") or ""
    elif kind == "lever":
        categories = item.get("categories") or {}
        row["department"] = categories.get("department") or ""
        row["team"] = categories.get("team") or ""
    elif kind == "workday":
        row["team"] = item.get("jobFamily") or ""
    # Remotive's broad board category is not an employer department.
    row.update(title=title, company=company, location=location, description=description, url=url,
               source="Remotive" if kind == "remotive" else f"{kind}: {company}", source_id=str(item.get("id") or item.get("id_icims") or ""),
               published_at=published, fetched_at=fetched_at,
               extraction_notes="Location and salary extraction is conservative; verify posting details. Greenhouse date is last updated, not necessarily publication.")
    row.update(location_fields(location, mode))
    row.update(salary_fields(raw_pay))
    return row


def collection_assessment(row, profile, result, minimum=None):
    """Score evidence quality for discovery; hard matching rules remain authoritative."""
    from job_preferences import normalize, role_matches
    assessed = dict(row)
    settings = profile.get("collection_confidence", {})
    minimum = int(settings.get("minimum", 60) if minimum is None else minimum)
    strong_minimum = int(settings.get("strong", 80))
    if result is None:
        assessed.update(collection_decision="rejected", rejection_reason="Failed title, workplace, compensation, or exclusion gate")
        return assessed

    title = normalize(row.get("title", ""))
    description = normalize(row.get("description", ""))
    location_text = normalize(row.get("location", ""))
    mode = row.get("work_mode", "").lower()
    acceptable_remote_region = re.search(r"\b(?:toronto|canada|north america|americas|anywhere|worldwide|global)\b", location_text)
    if mode == "remote" and location_text not in {"", "remote"} and not acceptable_remote_region:
        assessed.update(result)
        assessed.update(collection_decision="rejected", rejection_reason="Remote posting is tied to a region that does not include Canada",
                        application_readiness="rejected", manual_review_required="true")
        return assessed
    if (location_text and mode != "remote" and
            not re.search(r"\b(?:toronto|canada|anywhere|worldwide|global|north america)\b", location_text)):
        assessed.update(result)
        assessed.update(collection_decision="rejected", rejection_reason="Physical or unspecified work location is outside Toronto/Canada",
                        application_readiness="rejected", manual_review_required="true")
        return assessed
    direct = (bool(role_matches(row.get("title", ""), profile)) if profile.get("role_tracks") else
              any(re.search(r"\b" + re.escape(normalize(role)) + r"\b", title) for role in profile.get("roles", [])))
    department_assisted = result.get("discovery_method") == "department_and_description"
    role_score = 40 if direct else 28 if department_assisted else 0

    technical = bool(re.search(r"\b(?:sql|python|dbt|snowflake|looker|tableau|power bi|data model(?:ing|s)?)\b", description))
    analytical = bool(re.search(r"\b(?:analytics?|analysis|experimentation|a b test(?:ing|s)?|statistics?|forecasting|attribution|metrics?|kpis?|insights?)\b", description))
    responsibility_score = 20 if technical and analytical else 10 if technical or analytical else 0

    eligibility = row.get("canada_eligible", "").lower()
    location_score = 15 if eligibility == "true" and mode in {"remote", "hybrid"} else 10 if eligibility == "true" else 6 if mode == "remote" else 5

    employment_text = f"{title} {description}"
    permanent = bool(re.search(r"\b(?:permanent|regular|full time|fulltime|indefinite)\b", employment_text))
    employment_score = 10 if permanent else 5

    pay_status = result.get("compensation_status", "")
    low = float(row["salary_min"]) if str(row.get("salary_min", "")).strip() else None
    high = float(row["salary_max"]) if str(row.get("salary_max", "")).strip() else None
    target = profile.get("compensation", {})
    target_min = float(target.get("min", 175000))
    base_floor = float(target.get("minimum_base_cad", 160000))
    if low is None or high is None:
        compensation_score, compensation_interpretation = 4, "Low confidence: salary is missing or no single comparable annual CAD range was extracted"
    elif low >= target_min:
        compensation_score, compensation_interpretation = 15, f"Strong: entire CAD {low:,.0f}–{high:,.0f} range meets the {target_min:,.0f} target"
    elif low >= base_floor and high >= target_min:
        compensation_score, compensation_interpretation = 12, f"Good: range starts above the {base_floor:,.0f} base floor and reaches the {target_min:,.0f} target"
    elif high >= target_min:
        compensation_score, compensation_interpretation = 10, f"Possible: only the upper part of CAD {low:,.0f}–{high:,.0f} reaches the target"
    elif high >= base_floor:
        compensation_score, compensation_interpretation = 7, f"Below target: range reaches the base floor but not {target_min:,.0f} total cash"
    else:
        compensation_score, compensation_interpretation = 4, f"Below floor: CAD {low:,.0f}–{high:,.0f} does not reach the {base_floor:,.0f} base minimum"
    if high is not None and high < base_floor:
        assessed.update(result)
        assessed.update(role_confidence=role_score, responsibility_confidence=responsibility_score,
                        location_confidence=location_score, employment_confidence=employment_score,
                        compensation_confidence=4, compensation_interpretation=compensation_interpretation,
                        application_readiness="rejected", manual_review_required="true", collection_decision="rejected",
                        rejection_reason=f"Advertised CAD ceiling {high:,.0f} is below the {base_floor:,.0f} base minimum")
        return assessed

    total = role_score + responsibility_score + location_score + employment_score + compensation_score
    if re.search(r"\banalyst\b", title) and not analytical:
        total = min(total, minimum - 1)
    readiness = "high_confidence_match" if total >= strong_minimum else "review_required" if total >= minimum else "rejected"
    notes = []
    notes.append("Direct target title" if direct else "Department-assisted role discovery")
    notes.append("Technical and analytical responsibilities" if technical and analytical else
                 "Partial responsibility evidence" if technical or analytical else "No strong analytics responsibility evidence")
    notes.append("Canada eligibility and work mode confirmed" if location_score == 15 else "Location or work eligibility needs review")
    if not permanent:
        notes.append("Permanent/full-time status not explicit")
    if compensation_score == 4:
        notes.append("Target compensation not confirmed")
    essential_facts_confirmed = permanent and eligibility == "true" and mode in {"remote", "hybrid"} and compensation_score >= 10
    assessed.update(result)
    assessed.update(role_confidence=role_score, responsibility_confidence=responsibility_score,
                    location_confidence=location_score, employment_confidence=employment_score,
                    compensation_confidence=compensation_score, compensation_interpretation=compensation_interpretation, overall_confidence=total,
                    application_readiness=readiness, manual_review_required="false" if essential_facts_confirmed else "true",
                    admission_reasons="; ".join(notes), collection_decision="admitted" if total >= minimum else "rejected",
                    rejection_reason="" if total >= minimum else f"Confidence {total} is below collection minimum {minimum}")
    return assessed


def collect(args):
    # Imported here to keep the CLI and source adapter modules independent.
    from job_assistant import load_profile, match, write_csv
    profile = load_profile(args.profile)
    config = json.loads(args.sources.read_text(encoding="utf-8"))
    sources = config.get("sources") if isinstance(config, dict) else None
    if not isinstance(sources, list) or not sources:
        raise ValueError("sources.json needs a nonempty sources list")
    for source in sources:
        if not isinstance(source, dict):
            raise ValueError("Each source must be an object")
        endpoint(source)
    if args.output.resolve() in {args.profile.resolve(), args.sources.resolve()}:
        raise ValueError("Output must not overwrite profile or source configuration")
    rows, audit_rows, seen, failures, succeeded, scanned = [], [], set(), [], 0, 0
    for source in sources:
        label = source.get("company") or source.get("type")
        try:
            data, fetched_at, cached = fetch(source, args.cache_dir)
            batch = []
            for item in data["jobs"]:
                row = normalize_job(item, source, fetched_at)
                if row is not None:
                    result = match(row, profile, discovery=True)
                    assessed = collection_assessment(row, profile, result)
                    audit_rows.append(assessed)
                    if assessed["collection_decision"] == "admitted" and assessed["score"] >= args.min_score:
                        batch.append(assessed)
            succeeded += 1
            scanned += len(data["jobs"])
            for row in batch:
                if row["url"] not in seen:
                    seen.add(row["url"])
                    rows.append(row)
            print(f"{label}: {len(data['jobs'])} listings checked, {len(batch)} candidates ({'cached' if cached else 'live'})")
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
            failure = f"{label}: {error}"
            failures.append((source, failure))
            print(f"Source failed — {failure}")
    if not succeeded:
        raise ValueError("All sources failed. Existing jobs.csv was preserved. " + "; ".join(failure for _, failure in failures))
    required_failures = [failure for source, failure in failures if not source.get("optional", False)]
    if required_failures and args.output.exists():
        raise ValueError("Some sources failed; existing output preserved to avoid losing listings. Retry later or use --output jobs.partial.csv.")
    temp = args.output.with_suffix(args.output.suffix + ".tmp")
    write_csv(temp, FIELDS, rows)
    temp.replace(args.output)
    audit_output = getattr(args, "audit_output", args.output.with_name("jobs_audit.csv"))
    if audit_output:
        audit_temp = audit_output.with_suffix(audit_output.suffix + ".tmp")
        write_csv(audit_temp, AUDIT_FIELDS, audit_rows)
        audit_temp.replace(audit_output)
    rejected = sum(row.get("collection_decision") == "rejected" for row in audit_rows)
    print(f"Saved {len(rows)} candidates from {scanned} listings to {args.output}; {rejected} evaluated postings were rejected. Audit: {audit_output}.")
    if failures:
        print("WARNING: Partial coverage; optional sources failed: " + "; ".join(failure for _, failure in failures))
    print("Unknown compensation or eligibility stays eligible for review. Run the rank command next.")
