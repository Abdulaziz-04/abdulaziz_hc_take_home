# Avature Job Board Scraper

**A comprehensive web scraping pipeline for extracting job postings from Avature-powered career sites**

---

## 📋 Project Overview

This project implements an end-to-end solution for discovering, analyzing, and scraping job postings from companies using the Avature ATS (Applicant Tracking System) platform. Starting from 781,635 seed URLs, the system identifies Avature tenants, detects their API endpoints, and extracts job listings with intelligent duplicate detection.

### Final Results
- **Tenants Discovered**: 536 unique Avature tenants
- **Scrapable Endpoints**: 188 (179 full pagination + 9 partial)
- **Jobs Collected**: 5,630 unique jobs
- **Success Rate**: ~95% endpoint detection accuracy

---

## 🗂️ Project Structure

ABDULAZIZ_HC_TAKE_HOME/
├── data/
│ ├── Urls.txt # Original seed URLs (781,635 URLs)
│ ├── avature_tenants.csv # Discovered tenants (536 companies)
│ ├── expanded_urls.csv # CT-discovered additional tenants
│ ├── site_configs_raw.json # Detected endpoint configurations
│ ├── site_configs.csv # Human-readable endpoint configs
│ ├── avature_jobs.csv # Final scraped jobs (5,630)
│ └── avature_jobs.json # Jobs in JSON format
│
├── avature_discovery.ipynb # Phase 1: Tenant discovery
├── detect_endpoints.ipynb # Phase 2: API endpoint detection
├── extract_information.ipynb # Phase 3: Job extraction
├── helpers.py # Endpoint detection functions
├── jobs_helper.py # Job scraping functions
└── README.md # This file



---

## 🚀 Pipeline Stages

### Phase 1: Tenant Discovery (`avature_discovery.ipynb`)

**Goal**: Identify all unique Avature tenants from seed URLs

**Approach**:
1. **URL Parsing**: Extract tenant domains from 781,635 seed URLs
2. **Path Analysis**: Identify career-related paths (`/careers`, `/jobs`, `/talent`)
3. **Registry Building**: Create structured tenant registry with metadata

**Key Functions**:
- `extract_tenant_from_domain()`: Parse tenant names from subdomains
- `is_career_path()`: Classify URLs as career-related or not

**Output**:
- `avature_tenants.csv`: 2,546 total URLs from 536 unique tenants
- Career pages: 855 (33.5%)
- Non-career pages: 1,691 (66.5%)

**Additional Discovery**:
- **Certificate Transparency (CT)**: Discovered 28 additional tenants via crt.sh
- Expanded registry to 2,546 URLs across 564 tenants

---

### Phase 2: Endpoint Detection (`detect_endpoints.ipynb`)

**Goal**: Automatically detect which API endpoints each tenant supports

**Detection Methods** (Priority Order):

#### Method 1: PublicReports JSON API (Highest Priority)
- Pattern: `/PublicReports/{report_id}/json`
- Detection: Regex search in HTML + test request
- Advantages: Clean JSON, best pagination support
- Example: `https://boeing.avature.net/PublicReports/12345/json`

#### Method 2: SearchJobs HTML Endpoint (Medium Priority)
- Pattern: `/careers/SearchJobs` or similar
- Detection: Form action extraction + path guessing
- Pagination: `jobOffset` and `jobRecords` parameters
- Example: `https://ally.avature.net/careers/SearchJobs?jobOffset=0&jobRecords=50`

#### Method 3: HTML Job ID Extraction (Fallback)
- When no API found, extract job IDs from HTML
- Requires individual job detail page scraping
- Status: Marked as "partial" (9 tenants)

**Concurrency & Rate Limiting**:
- ThreadPoolExecutor with 10 workers
- Token bucket rate limiter (20 requests/second)
- Automatic retry logic with exponential backoff

**Results**:
- **SUCCESS**: 179 tenants (full pagination support)
- **PARTIAL**: 9 tenants (HTML scraping required)
- **FAILED**: 376 tenants (inactive/inaccessible)
- **Total Scrapable**: 188 tenants (33.3% success rate)

---

### Phase 3: Job Extraction (`extract_information.ipynb`)

**Goal**: Scrape job listings from detected endpoints with intelligent duplicate handling

- Ended up retrieving 5,630 jobs in total after deduplicating out of 46,000 jobs
- I had retrieved 15,000 jobs earlier with job desciptions, I am not sure what happened in the workflow and I was unable to recreate it effectively.

