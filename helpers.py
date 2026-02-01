"""
Helper functions and classes for Avature scraper
"""

import requests
from bs4 import BeautifulSoup
import re
import time
import logging
from urllib.parse import urljoin
from typing import Dict, Optional, Tuple
from threading import Lock

# Setup logging
logger = logging.getLogger(__name__)

# Constants
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


class RateLimiter:
    """Thread-safe token bucket rate limiter"""

    def __init__(self, requests_per_second: int):
        self.rate = requests_per_second
        self.tokens = requests_per_second
        self.last_update = time.time()
        self.lock = Lock()

    def acquire(self):
        """Acquire permission to make a request (blocks if necessary)"""
        with self.lock:
            now = time.time()
            elapsed = now - self.last_update
            self.tokens = min(self.rate, self.tokens + elapsed * self.rate)
            self.last_update = now

            if self.tokens >= 1:
                self.tokens -= 1
                return
            else:
                sleep_time = (1 - self.tokens) / self.rate
                time.sleep(sleep_time)
                self.tokens = 0


def fetch_page(
    url: str, rate_limiter: RateLimiter, timeout: int = 15, max_retries: int = 2
) -> Optional[Tuple[int, str, str]]:
    """
    Fetch a page with rate limiting and retries

    Args:
        url: URL to fetch
        rate_limiter: RateLimiter instance to control request rate
        timeout: Request timeout in seconds
        max_retries: Number of retry attempts

    Returns:
        Tuple of (status_code, html_content, final_url) or None on failure
    """
    rate_limiter.acquire()

    for attempt in range(max_retries):
        try:
            response = requests.get(
                url, headers=HEADERS, timeout=timeout, allow_redirects=True
            )
            return (response.status_code, response.text, response.url)
        except requests.Timeout:
            logger.warning(
                f"Timeout fetching {url} (attempt {attempt + 1}/{max_retries})"
            )
        except requests.RequestException as e:
            logger.warning(f"Error fetching {url}: {e}")
            break
    return None


def detect_public_reports_endpoint(
    html: str, tenant: str, rate_limiter: RateLimiter
) -> Optional[Dict]:
    """
    Detect Avature PublicReports JSON endpoint

    Args:
        html: HTML content to search
        tenant: Tenant domain (e.g., 'boeing.avature.net')
        rate_limiter: RateLimiter instance for test requests

    Returns:
        Config dict if found, None otherwise
    """
    pattern = r"/PublicReports/(\d+)/json"
    matches = re.findall(pattern, html)

    if matches:
        report_id = matches[0]
        endpoint_url = f"https://{tenant}/PublicReports/{report_id}/json"

        try:
            rate_limiter.acquire()
            test_response = requests.get(
                f"{endpoint_url}?offset=0&recordsPerPage=1", headers=HEADERS, timeout=10
            )
            if test_response.status_code == 200:
                data = test_response.json()
                if "rows" in data or "data" in data:
                    return {
                        "type": "public_report_json",
                        "endpoint": endpoint_url,
                        "pagination_param": "offset",
                        "page_size_param": "recordsPerPage",
                        "default_page_size": 1000,
                        "confidence": "high",
                        "test_status": "success",
                    }
        except Exception as e:
            logger.debug(f"PublicReports test failed for {tenant}: {e}")

    return None


def detect_search_jobs_endpoint(
    html: str, soup: BeautifulSoup, tenant: str, rate_limiter: RateLimiter
) -> Optional[Dict]:
    """
    Detect SearchJobs HTML endpoint

    Args:
        html: HTML content
        soup: BeautifulSoup parsed HTML
        tenant: Tenant domain
        rate_limiter: RateLimiter instance

    Returns:
        Config dict if found, None otherwise
    """
    # Method 1: Form detection
    forms = soup.find_all("form", action=re.compile(r"SearchJobs", re.I))
    if forms:
        action = forms[0].get("action", "")
        base_url = f"https://{tenant}"
        endpoint = urljoin(base_url, action)
        return {
            "type": "search_jobs_html",
            "endpoint": endpoint,
            "pagination_param": "jobOffset",
            "page_size_param": "jobRecords",
            "default_page_size": 50,
            "confidence": "medium",
            "method": "form_detection",
        }

    # Method 2: Path guessing
    if "SearchJobs" in html:
        common_paths = ["/careers/SearchJobs/", "/careers/SearchJobs", "/SearchJobs/"]
        for path in common_paths:
            test_url = f"https://{tenant}{path}"
            try:
                rate_limiter.acquire()
                test_resp = requests.head(
                    test_url, headers=HEADERS, timeout=5, allow_redirects=True
                )
                if test_resp.status_code == 200:
                    return {
                        "type": "search_jobs_html",
                        "endpoint": test_url,
                        "pagination_param": "jobOffset",
                        "page_size_param": "jobRecords",
                        "default_page_size": 50,
                        "confidence": "medium",
                        "method": "path_guessing",
                    }
            except:
                pass

    return None


def detect_job_ids_in_html(html: str, soup: BeautifulSoup, url: str) -> Optional[Dict]:
    """
    Fallback: Extract job IDs from HTML

    Args:
        html: HTML content
        soup: BeautifulSoup parsed HTML
        url: Page URL

    Returns:
        Config dict if job IDs found, None otherwise
    """
    job_id_patterns = [
        r"jobId[=:](\d+)",
        r'data-job-id["\s]*=["\s]*(\d+)',
        r"/JobDetail/[^/]+/(\d+)",
    ]

    all_job_ids = set()
    for pattern in job_id_patterns:
        matches = re.findall(pattern, html)
        all_job_ids.update(matches)

    if all_job_ids:
        return {
            "type": "html_scrape",
            "endpoint": url,
            "job_count_estimate": len(all_job_ids),
            "confidence": "low",
            "sample_job_ids": list(all_job_ids)[:5],
            "note": "Requires detail page crawling",
        }

    return None


def detect_endpoint_for_url(
    tenant: str, url: str, is_career_page: bool, rate_limiter: RateLimiter
) -> Dict:
    """
    Main detection function for a single tenant URL

    Args:
        tenant: Tenant domain
        url: Full career page URL
        is_career_page: Whether this is a career-focused page
        rate_limiter: RateLimiter instance

    Returns:
        Detection result dict
    """
    result = {
        "tenant": tenant,
        "career_url": url,
        "is_career_page": is_career_page,
        "status": "failed",
        "type": None,
        "endpoint": None,
        "confidence": None,
    }

    # Fetch page
    page_data = fetch_page(url, rate_limiter)

    if not page_data:
        result["error"] = "fetch_failed"
        return result

    status_code, html, final_url = page_data

    if status_code != 200:
        result["error"] = f"http_{status_code}"
        return result

    soup = BeautifulSoup(html, "html.parser")

    # Try detection methods in priority order
    config = detect_public_reports_endpoint(html, tenant, rate_limiter)
    if config:
        result.update(config)
        result["status"] = "success"
        return result

    config = detect_search_jobs_endpoint(html, soup, tenant, rate_limiter)
    if config:
        result.update(config)
        result["status"] = "success"
        return result

    config = detect_job_ids_in_html(html, soup, url)
    if config:
        result.update(config)
        result["status"] = "partial"
        return result

    result["error"] = "no_pattern_detected"
    return result
