"""
Helper functions for Avature job scraping
"""

import requests
import time
import random
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin
import re
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
    "Referer": "https://www.google.com/",
}

REQUEST_TIMEOUT = 15
MAX_PAGES_PER_SITE = 20


def clean_text(text):
    """Clean extracted text"""
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def extract_job_id_from_url(url):
    """Extract job ID from URL"""
    if not url:
        return None

    patterns = [
        r"/(\d{4,})",
        r"jobId=(\d+)",
        r"id=(\d+)",
    ]

    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)

    return None


def parse_job_from_listing(job_elem, base_url, tenant):
    """
    Parse job info from a list item
    """
    try:
        job_data = {
            "tenant": tenant,
            "job_title": None,
            "job_url": None,
            "job_id": None,
            "location": None,
            "date_posted": None,
            "job_description": None,
            "scraped_at": datetime.now().isoformat(),
        }

        # Find ANY link in the element
        title_link = job_elem.find("a", href=True)

        if title_link:
            job_data["job_title"] = clean_text(title_link.get_text())
            job_data["job_url"] = urljoin(base_url, title_link["href"])
            job_data["job_id"] = extract_job_id_from_url(job_data["job_url"])

        # Extract ALL text from element, look for location patterns
        element_text = job_elem.get_text()

        # Common location patterns
        location_match = re.search(
            r"(?:Location|City|Office)[\s:]+([^|;\n]+)", element_text, re.I
        )
        if location_match:
            job_data["location"] = clean_text(location_match.group(1))
        else:
            location_elem = job_elem.find(
                string=re.compile(
                    r"\b(New York|London|Tokyo|Singapore|Hong Kong|US|UK|Remote)\b",
                    re.I,
                )
            )
            if location_elem:
                job_data["location"] = clean_text(location_elem)

        return job_data if job_data["job_title"] else None

    except Exception as e:
        logger.debug(f"Error parsing job element: {e}")
        return None


def parse_job_from_json(job_obj, tenant, base_url):
    """
    Parse job from JSON response
    """
    try:
        job_data = {
            "tenant": tenant,
            "job_title": None,
            "job_url": None,
            "job_id": None,
            "location": None,
            "date_posted": None,
            "job_description": None,
            "scraped_at": datetime.now().isoformat(),
        }

        # Extract job ID
        job_id = (
            job_obj.get("id")
            or job_obj.get("jobId")
            or job_obj.get("Id")
            or job_obj.get("requisitionId")
            or job_obj.get("positionId")
        )

        if job_id:
            job_data["job_id"] = str(job_id)

        # Extract title
        job_data["job_title"] = (
            job_obj.get("title")
            or job_obj.get("jobTitle")
            or job_obj.get("positionTitle")
            or job_obj.get("name")
        )

        # Extract location
        location_data = (
            job_obj.get("location")
            or job_obj.get("primaryLocation")
            or job_obj.get("city")
        )
        if isinstance(location_data, dict):
            location_parts = []
            for key in ["city", "state", "country", "region"]:
                if location_data.get(key):
                    location_parts.append(str(location_data[key]))
            job_data["location"] = ", ".join(location_parts) if location_parts else None
        elif location_data:
            job_data["location"] = str(location_data)

        # Extract description
        job_data["job_description"] = (
            job_obj.get("description")
            or job_obj.get("summary")
            or job_obj.get("jobDescription")
        )

        # Build job URL
        if job_id:
            title_slug = (
                job_data["job_title"].replace(" ", "-")
                if job_data["job_title"]
                else "job"
            )
            title_slug = re.sub(r"[^a-zA-Z0-9-]", "", title_slug)[:50]

            url_candidates = [
                job_obj.get("url"),
                job_obj.get("jobUrl"),
                job_obj.get("applyUrl"),
                f"{base_url}/JobDetail/{title_slug}/{job_id}",
                f"{base_url}/jobs/JobDetail/{job_id}",
            ]

            for url in url_candidates:
                if url:
                    job_data["job_url"] = (
                        urljoin(base_url, url) if not url.startswith("http") else url
                    )
                    break

        # Extract date posted
        date_posted = (
            job_obj.get("postedDate")
            or job_obj.get("datePosted")
            or job_obj.get("createdDate")
        )
        if date_posted:
            job_data["date_posted"] = str(date_posted)

        return job_data if job_data["job_title"] else None

    except Exception as e:
        logger.debug(f"Error parsing JSON job: {e}")
        return None


def find_job_elements(soup):
    """
    Find job elements in HTML with multiple fallback strategies
    """
    job_elements = []

    # Method 1: Find all links with job-related hrefs
    job_links = soup.find_all("a", href=re.compile("JobDetail|job|position", re.I))

    if job_links:
        for link in job_links:
            parent = link.find_parent(["li", "div", "article", "tr", "section"])

            if parent and parent not in job_elements:
                job_elements.append(parent)
            elif link not in job_elements:
                job_elements.append(link)

    # Method 2: If method 1 found nothing, try class-based
    if not job_elements:
        patterns = [
            ("li", {"class": re.compile("job|result|item", re.I)}),
            ("div", {"class": re.compile("job|result|card", re.I)}),
            ("article", {}),
            ("tr", {"class": re.compile("job", re.I)}),
        ]

        for tag, attrs in patterns:
            job_elements = soup.find_all(tag, attrs)
            if job_elements:
                break

    return job_elements


def try_json_api(tenant, endpoint, offset=0, limit=50):
    """
    Try to fetch jobs as JSON from API endpoints
    """
    base_url = (
        endpoint.split("SearchJobs")[0]
        if "SearchJobs" in endpoint
        else endpoint.rsplit("/", 1)[0]
    )

    api_urls = [
        f"{base_url}/PublicReports?actionPerformed=getJobsForCareerPage&jobOffset={offset}&jobRecords={limit}",
        f"{endpoint}?output=json&jobOffset={offset}&jobRecords={limit}",
        f"{base_url}/api/jobs?offset={offset}&limit={limit}",
    ]

    for api_url in api_urls:
        try:
            response = requests.get(
                api_url,
                headers={**HEADERS},
                timeout=REQUEST_TIMEOUT,
                allow_redirects=True,
            )

            if response.status_code == 200:
                try:
                    data = response.json()

                    if isinstance(data, dict) and (
                        "jobs" in data or "items" in data or "results" in data
                    ):
                        logger.info(f"  Found JSON API for {tenant}")
                        return api_url, data
                    elif isinstance(data, list) and len(data) > 0:
                        logger.info(f"  Found JSON API for {tenant}")
                        return api_url, data

                except ValueError:
                    continue

        except Exception:
            continue

    return None, None


def scrape_via_json_api(
    tenant, api_url_template, pagination_param, page_size_param, page_size
):
    """
    Scrape using JSON API with duplicate detection
    """
    import time

    jobs = []
    page = 0
    consecutive_empty = 0
    seen_job_ids = set()  # ← Track all job IDs we've seen

    while page < MAX_PAGES_PER_SITE:
        offset = page * page_size

        if "{offset}" in api_url_template:
            api_url = api_url_template.format(offset=offset, limit=page_size)
        else:
            api_url = re.sub(
                f"{pagination_param}=\\d+",
                f"{pagination_param}={offset}",
                api_url_template,
            )
            api_url = re.sub(
                f"{page_size_param}=\\d+", f"{page_size_param}={page_size}", api_url
            )

        try:
            response = requests.get(
                api_url,
                headers={**HEADERS},
                timeout=REQUEST_TIMEOUT,
            )

            if response.status_code != 200:
                break

            data = response.json()
            page_jobs = []
            jobs_list = []

            if isinstance(data, list):
                jobs_list = data
            elif isinstance(data, dict):
                jobs_list = (
                    data.get("jobs")
                    or data.get("items")
                    or data.get("results")
                    or data.get("data")
                    or data.get("jobList")
                    or []
                )

            base_url = (
                api_url.split("PublicReports")[0]
                if "PublicReports" in api_url
                else api_url.rsplit("/", 1)[0]
            )

            # Track duplicates on THIS page
            page_duplicates = 0
            page_new_jobs = 0

            for job_obj in jobs_list:
                job_data = parse_job_from_json(job_obj, tenant, base_url)
                if job_data:
                    job_id = job_data.get("job_id")

                    # Check if we've seen this job before
                    if job_id and job_id in seen_job_ids:
                        page_duplicates += 1
                        continue  # Skip duplicate

                    # New job - add it
                    if job_id:
                        seen_job_ids.add(job_id)
                    page_jobs.append(job_data)
                    page_new_jobs += 1

            # If >80% of jobs on this page are duplicates, stop
            if len(jobs_list) > 0:
                duplicate_rate = page_duplicates / len(jobs_list)
                if duplicate_rate > 0.8:
                    logger.warning(
                        f"{tenant}: Page {page+1} has {duplicate_rate*100:.0f}% duplicates - "
                        f"API not respecting pagination, stopping"
                    )
                    break

            # If NO new jobs found, increment empty counter
            if page_new_jobs == 0:
                consecutive_empty += 1
                if consecutive_empty >= 2:
                    logger.info(f"{tenant}: No new jobs for 2 pages, stopping")
                    break
            else:
                consecutive_empty = 0

            jobs.extend(page_jobs)
            logger.info(
                f"{tenant}: Page {page+1} - {page_new_jobs} new jobs, "
                f"{page_duplicates} duplicates (total: {len(jobs)})"
            )

            page += 1
            time.sleep(random.uniform(2.0, 4.0))  # Increased delay

        except Exception as e:
            logger.error(f"{tenant}: API error on page {page} - {e}")
            break

    logger.info(f"{tenant}: Collected {len(jobs)} unique jobs via JSON API")
    return jobs


def scrape_via_html_parsing(
    tenant, endpoint, pagination_param, page_size_param, page_size
):
    """
    Scrape using HTML parsing with duplicate detection
    """
    import time

    jobs = []
    page = 0
    consecutive_empty = 0
    seen_job_ids = set()

    while page < MAX_PAGES_PER_SITE:
        offset = page * page_size
        separator = "&" if "?" in endpoint else "?"
        url = f"{endpoint}{separator}{pagination_param}={offset}&{page_size_param}={page_size}"

        try:
            response = requests.get(
                url, headers=HEADERS, timeout=REQUEST_TIMEOUT, allow_redirects=True
            )

            soup = BeautifulSoup(response.content, "html.parser")
            job_elements = find_job_elements(soup)

            if not job_elements:
                consecutive_empty += 1
                if consecutive_empty >= 2:
                    logger.info(f"{tenant}: No more jobs at page {page}")
                    break
                page += 1
                time.sleep(random.uniform(2.0, 4.0))
                continue

            page_jobs = []
            page_duplicates = 0  # ← Add this

            for job_elem in job_elements:
                job_data = parse_job_from_listing(job_elem, endpoint, tenant)
                if job_data:
                    job_id = job_data.get("job_id")

                    # Check for duplicates
                    if job_id and job_id in seen_job_ids:
                        page_duplicates += 1
                        continue

                    if job_id:
                        seen_job_ids.add(job_id)
                    page_jobs.append(job_data)

            # Stop if mostly duplicates
            if len(job_elements) > 0 and page_duplicates / len(job_elements) > 0.8:
                logger.warning(
                    f"{tenant}: Page {page+1} has {page_duplicates}/{len(job_elements)} duplicates, stopping"
                )
                break

            if not page_jobs:
                consecutive_empty += 1
                if consecutive_empty >= 2:
                    break
            else:
                consecutive_empty = 0

            jobs.extend(page_jobs)
            logger.info(
                f"{tenant}: Page {page+1} - {len(page_jobs)} new jobs, "
                f"{page_duplicates} duplicates (total: {len(jobs)})"
            )

            page += 1
            time.sleep(random.uniform(2.0, 4.0))

        except Exception as e:
            logger.error(f"{tenant}: Error on page {page} - {e}")
            break

    logger.info(f"{tenant}: Collected {len(jobs)} unique jobs via HTML")
    return jobs


def scrape_paginated_endpoint(config):
    """
    Main scraper: tries JSON API first, falls back to HTML
    """
    tenant = config["tenant"]
    endpoint = config["endpoint"]
    pagination_param = config.get("pagination_param", "jobOffset")
    page_size_param = config.get("page_size_param", "jobRecords")
    default_page_size = int(config.get("default_page_size", 50))

    logger.info(f"Scraping {tenant}...")

    # Try JSON API first
    api_url, sample_data = try_json_api(tenant, endpoint, 0, default_page_size)

    if api_url:
        return scrape_via_json_api(
            tenant, api_url, pagination_param, page_size_param, default_page_size
        )

    # Fall back to HTML parsing
    return scrape_via_html_parsing(
        tenant, endpoint, pagination_param, page_size_param, default_page_size
    )


def scrape_partial_endpoint(config):
    """
    Scrape jobs from PARTIAL endpoint (requires detail page crawling)
    """

    tenant = config["tenant"]
    career_url = config["career_url"]
    sample_job_ids = config.get("sample_job_ids", [])

    if not sample_job_ids:
        logger.warning(f"  {tenant}: No job IDs available for partial scraping")
        return []

    logger.info(f"Scraping {tenant} (partial - {len(sample_job_ids)} jobs)...")

    jobs = []

    for job_id in sample_job_ids:
        job_url = f"{career_url}/JobDetail/{job_id}"

        try:
            response = requests.get(
                job_url, headers=HEADERS, timeout=REQUEST_TIMEOUT, allow_redirects=True
            )

            if "login" in response.url.lower() or "signin" in response.url.lower():
                logger.warning(f"  {tenant}: Job {job_id} requires auth")
                continue

            if response.status_code != 200:
                continue

            soup = BeautifulSoup(response.content, "html.parser")

            job_data = {
                "tenant": tenant,
                "job_title": None,
                "job_url": job_url,
                "job_id": job_id,
                "location": None,
                "date_posted": None,
                "job_description": None,
                "scraped_at": datetime.now().isoformat(),
            }

            title_elem = soup.find("h1") or soup.find(
                class_=re.compile("job.*title", re.I)
            )
            if title_elem:
                job_data["job_title"] = clean_text(title_elem.get_text())

            location_elem = soup.find(class_=re.compile("location", re.I))
            if location_elem:
                job_data["location"] = clean_text(location_elem.get_text())

            desc_elem = soup.find(
                class_=re.compile("description|content|summary|details", re.I)
            )
            if desc_elem:
                job_data["job_description"] = clean_text(desc_elem.get_text())

            if job_data["job_title"]:
                jobs.append(job_data)

            time.sleep(random.uniform(2.0, 4.0))

        except Exception as e:
            logger.debug(f"Error scraping job {job_id}: {e}")
            continue

    logger.info(f"{tenant}: Collected {len(jobs)} jobs from partial")
    return jobs


def scrape_single_config(config):
    """
    Wrapper to handle both success and partial configs
    """
    try:
        if config["status"] == "success":
            return scrape_paginated_endpoint(config)
        elif config["status"] == "partial":
            return scrape_partial_endpoint(config)
        else:
            return []
    except Exception as e:
        logger.error(f"Error scraping {config['tenant']}: {e}")
        return []
