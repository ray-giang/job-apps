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
          "salary_basis", "salary_raw", "source", "source_id", "published_at", "fetched_at",
          "location_evidence", "extraction_notes", "department", "team", "discovery_method", "discovery_evidence", "review_notes"]


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
    """Extract one explicit annual CAD range; leave ambiguous bands untouched."""
    result = {"salary_raw": raw, "salary_min": "", "salary_max": "", "salary_currency": "", "salary_period": "", "salary_basis": ""}
    # Location-tiered or multiple-currency pay needs human interpretation.
    lines = [line for line in raw.splitlines() if re.search(r"\bCAD\b|CA\$|C\$", line, re.I)]
    if len(lines) != 1 or re.search(r"\bUSD\b|US\$|\bEUR\b|\bGBP\b", lines[0], re.I):
        return result
    line = lines[0]
    if not re.search(r"annual|annum|year", line, re.I):
        return result
    amount = r"(?:\d{1,3}(?:,\d{3})+|\d{3,6})(?:\.\d+)?\s*[kK]?"
    ranges = list(re.finditer(r"(?P<low>" + amount + r")\s*(?:CAD|CA\$|C\$)?\s*(?:-|–|—|to)\s*(?:CAD\s*|CA\$|C\$|\$)?(?P<high>" + amount + r")", line))
    if len(ranges) != 1:
        return result
    def convert(value):
        value = value.replace(",", "").replace(" ", "").lower()
        return float(value.rstrip("k")) * (1000 if value.endswith("k") else 1)
    low, high = (convert(ranges[0][name]) for name in ("low", "high"))
    if not 10000 <= low <= high <= 2000000:
        return result
    basis = "total_cash" if re.search(r"total cash", line, re.I) else "base" if re.search(r"base salary|base pay", line, re.I) else ""
    result.update(salary_min=low, salary_max=high, salary_currency="CAD", salary_period="annual", salary_basis=basis)
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
    rows, seen, failures, succeeded, scanned = [], set(), [], 0, 0
    for source in sources:
        label = source.get("company") or source.get("type")
        try:
            data, fetched_at, cached = fetch(source, args.cache_dir)
            batch = []
            for item in data["jobs"]:
                row = normalize_job(item, source, fetched_at)
                if row is not None:
                    result = match(row, profile, discovery=True)
                    if result is not None and result["score"] >= args.min_score:
                        for field in ("discovery_method", "discovery_evidence", "review_notes"):
                            row[field] = result[field]
                        batch.append(row)
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
    print(f"Saved {len(rows)} candidates from {scanned} listings to {args.output}.")
    if failures:
        print("WARNING: Partial coverage; optional sources failed: " + "; ".join(failure for _, failure in failures))
    print("Unknown compensation or eligibility stays eligible for review. Run the rank command next.")
