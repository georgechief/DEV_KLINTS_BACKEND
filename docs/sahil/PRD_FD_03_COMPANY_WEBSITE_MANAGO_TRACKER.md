# PRD — Company website SalesManago / Manago tracker scrape

**Status:** Ready for implementation (check ID corrected)  
**Owner track:** Sahil (`docs/sahil/`)  
**Check ID:** `FD-07` (employer correction — not FD-03)  
**Filename note:** Historical filename still says FD-03; implement under **FD-07**.  
**Depends on:**  
- `Company.domain` populated (signup / Settings website — `company_domain`; see Maheep AUTH-01)  
- DCS foundation executor wiring (`dataruns/dcs/executors/foundation.py`, DCS-01 orchestrate)  
- Excel FD-07 VISIT / smclient path remains required alongside this scrape  
**Repos:** Python HTML scraper + FD-07 executor (scrape + signals)  
**Also:** FD-03 stays **ERP** and is marked **`isOptional=true`** (FE-03) — do not put scrape on FD-03.

**Scope:** Fetch the company’s public website HTML and contribute PASS when SalesManago / Manago tracking script markers are present in page **source code** (string match in scraped HTML / inline scripts — not DOM element presence alone). Combine with VISIT/smclient signals per Excel sheet 02.

---

## 0. Check-master alignment (read first)

| Today in `CHECK_MASTER_42.md` | Name |
|-------------------------------|------|
| **FD-03** | ERP feed reachable and parseable → keep; `isOptional=true` |
| **FD-07** | Manago site tracking code active → VISIT/smclient **+** this website scrape |

**Do not** redefine FD-03 as website scrape. Legacy ERP `erp_in_scope` / `NOT_CONNECTED` / `ERP_OUT_OF_SCOPE` behavior for FD-03 remains.

| Field | Value for scrape work |
|-------|-----------|
| `check_id` | `FD-07` |
| Check name | Manago site tracking code active |
| Systems | Manago + Storefront (+ company website) |
| Role | `GATE` |
| `isOptional` | `false` (required gate; FD-03 is the optional one) |
| Weight | `0` |

---

## 1. Problem

Manago.ai (SalesManago) tracking is installed as a JS snippet on the brand’s public site. Klints already stores the brand site as **`Company.domain`** (API field `company_domain`, Settings label **Website**), but FD-03 today only reasons about ERP scope and never looks at that website.

We need a live gate that:

1. Reads the tenant company’s website domain.  
2. Scrapes the page HTML with a Python scraper.  
3. Searches the **raw HTML / script source** for SalesManago tracker markers (e.g. `www.salesmanago.pl`, `_smid`, `sm.js`).  
4. Emits FD-03 **PASS** when the tracker is present, **FAIL** when the site is reachable but the tracker is missing.

Because FD-03 is **optional** (`isOptional=true`), FAIL must not block the dashboard / headline the way required gates (FD-01/FD-02) do.

---

## 2. Goal

1. Extend `evaluate_fd_07` with website scrape using `Company.domain` (keep VISIT/smclient).  
2. Add a small scraper module (HTTP GET → HTML text → marker scan).  
3. Persist evidence (URL fetched, which markers matched, snippet excerpt).  
4. Separately: mark FD-03 ERP as `isOptional=true` for assemble / app-lock.

---

## 3. Source of truth — company website

| Concept | Storage / API |
|---------|----------------|
| Canonical field | `tenants.Company.domain` |
| Register / Settings body | `company_domain` |
| UI label | **Website** |
| Normalized form | lowercase host, strip `http://` / `https://` / trailing `/` (same as workspace normalize) |

**Fetch URL construction**

```text
raw = company.domain  # e.g. "lumera.skin" or leftover "https://lumera.skin"
host = normalize_company_domain(raw)
if not host → MISSING_INPUT (no scrape)
url = "https://" + host
# optional fallback: if https fails with connection error, retry "http://" + host once
```

Prefer **https**. Do not invent a domain from the user’s email.

---

## 4. Tracker markers (PASS if any match)

Scan the **full scraped response body as text** (HTML + inline `<script>` contents). Case-insensitive substring match unless noted.

### 4.1 Primary markers (any one → tracker considered present)

| Marker | Why |
|--------|-----|
| `www.salesmanago.pl` | Classic SM loader host in snippet |
| `salesmanago.pl/static/sm.js` | Script URL path |
| `www.salesmanago.com` | Alternate regional host if present |
| `app.salesmanago.com` | Cloud / app host variants |
| `_smid` | SM client id variable |
| `SalesmanagoObject` | SM bootstrap global |
| `sm.js` **and** (`salesmanago` in same document) | Loader filename plus brand string (avoid bare `sm.js` false positives alone) |

### 4.2 Example install (PASS)

If the scraped HTML contains a block like the following (or equivalent), FD-03 **PASS**:

```html
<script type="text/javascript">
    var _smid = "58b12a8ce6013316";
    var _smapp = 1;
    var _smcsec = true;
    (function(w, r, a, sm, s) {
        w['SalesmanagoObject'] = r;
        w[r] = w[r] || function () {( w[r].q = w[r].q || [] ).push(arguments)};
        sm = document.createElement('script'); sm.type = 'text/javascript'; sm.async = true; sm.src = a;
        s = document.getElementsByTagName('script')[0];
        s.parentNode.insertBefore(sm, s);
    })(window, 'sm', ('https:' == document.location.protocol ? 'https://' : 'http://') + 'www.salesmanago.pl/static/sm.js');
</script>
```

Matched markers in this sample: `_smid`, `SalesmanagoObject`, `www.salesmanago.pl`, `salesmanago.pl/static/sm.js`.

### 4.3 What “scrape the code” means

- Operate on **response text** (HTML source), not a headless browser click path for MVP.  
- Do **not** require parsing into DOM elements and querying nodes; string / regex over source is enough.  
- Optionally extract `<script>...</script>` blocks first, then scan those strings — still code/source, not “element exists in rendered tree”.  
- Out of scope for MVP: executing JS, waiting for tag-manager injected scripts that never appear in first HTML.

If the brand only injects SM via GTM after JS runs and the first HTML has **no** markers → FAIL (or UNKNOWN with reason `TRACKER_NOT_IN_STATIC_HTML` if product prefers — default **FAIL** when HTML fetched OK).

---

## 5. Scraper contract (Python)

Suggested module: `dataruns/dcs/scrapers/company_website.py` (or `tenants/website_scrape.py` if reused outside DCS).

```text
scrape_company_website(url: str) -> WebsiteScrapeResult
```

| Field | Meaning |
|-------|---------|
| `ok` | HTTP completed with body |
| `final_url` | After redirects |
| `status_code` | e.g. 200 |
| `html` | Response text (cap size, e.g. 2 MB) |
| `error` | timeout / DNS / TLS / too large |

**HTTP rules**

- Method: `GET`  
- Timeout: e.g. 10–15s connect+read  
- User-Agent: identifiable Klints bot string  
- Follow redirects (max small, e.g. 5)  
- No auth cookies required for public homepage  
- Do not download binary assets; HTML only  

**Marker scan**

```text
find_salesmanago_markers(html: str) -> list[str]  # matched marker keys
tracker_active = len(matches) > 0
```

Use recorded HTML fixtures in unit tests (do not hit live sites in CI).

---

## 6. FD-03 outcome table

| Condition | `status` | `reason_code` (example) |
|-----------|----------|-------------------------|
| `Company.domain` missing / empty / `localhost` | `UNKNOWN` | `MISSING_INPUT:company_website` |
| Scrape transport failure (DNS, timeout, TLS) | `UNKNOWN` | `WEBSITE_UNREACHABLE` |
| HTTP 4xx/5xx after retries | `FAIL` or `UNKNOWN` | `WEBSITE_HTTP_ERROR` (prefer UNKNOWN if unsure site identity) |
| HTML OK, **no** markers | `FAIL` | `RC-12` (tracking / monitoring code inactive) |
| HTML OK, **≥1** marker | `PASS` | — |

Confidence: PASS/FAIL with clear markers → `HIGH`; UNKNOWN network → `LOW`.

**Optional gate:** FAIL does **not** set assemble `BLOCKED` for app lock when only FD-03 fails (`isOptional=true`). Still persist FAIL in `check_results` and surface as a soft issue on the gated dashboard.

---

## 7. Executor wiring

Extend `evaluate_fd_07` in `dataruns/dcs/executors/foundation.py` (do not replace ERP `evaluate_fd_03`).

```text
1. Load company for DCS run (already on orchestration context)
2. Resolve website URL from Company.domain
3. scrape_company_website(url)
4. find_salesmanago_markers(html)
5. Combine with VISIT/smclient signals → CheckResult FD-07 + evidence
```

### 7.1 Evidence shape

```json
{
  "source": "company_website",
  "locator": "https://lumera.skin/",
  "value": {
    "final_url": "https://lumera.skin/",
    "status_code": 200,
    "markers_matched": ["_smid", "www.salesmanago.pl", "SalesmanagoObject"],
    "snippet": "var _smid = \"58b12a8ce6013316\"; ... www.salesmanago.pl/static/sm.js"
  },
  "observed_at": "2026-07-30T05:00:00Z"
}
```

Truncate `snippet` (e.g. 280 chars). Never store full page HTML on `RunScore` if oversized — keep markers + short excerpt.

### 7.2 Orchestration note

Scrape is network I/O: run inside the DCS Celery task (same as other gates). Cache per-run only (do not scrape twice in one `run_dcs_score`). Respect timeouts so one bad site cannot hang the whole run indefinitely.

---

## 8. Check master / seed updates

1. Set FD-03 display name → website Manago/SalesManago tracker present.  
2. Systems compared → `Company website + Manago` (or `Storefront + Manago`).  
3. `isOptional` / `is_optional` = `true` for FD-03.  
4. Root causes: keep / prefer `RC-12` (monitoring / tracking).  
5. Update `docs/dcs_scoring/CHECK_MASTER_42.md` row for FD-03.  
6. Update DCS-02 inventory row for FD-03 to point at this PRD (ERP path removed).

---

## 9. Files to change (implementation)

| Area | File |
|------|------|
| Scraper | `dataruns/dcs/scrapers/company_website.py` (new) |
| Executor | `dataruns/dcs/executors/foundation.py` — rewrite `evaluate_fd_03` |
| Context | Pass `company.domain` (or prebuilt website URL) into foundation context |
| Fixtures | HTML samples with / without SM snippet under `dataruns/tests/fixtures/website/` |
| Tests | `dataruns/tests/test_fd_03_website_tracker.py` |
| Seed / master | `check_master_mvp1.json`, `seed_dcs_master`, `CHECK_MASTER_42.md` |
| Docs | DCS-02 FD-03 row → link this PRD |

---

## 10. Acceptance

1. Company with `domain=example.com` and homepage HTML containing the sample `_smid` + `www.salesmanago.pl/static/sm.js` snippet → FD-03 **PASS**; evidence lists matched markers.  
2. Same domain, HTML without any markers → FD-03 **FAIL** (`RC-12`); app shell **not** hard-blocked solely for this FAIL (`isOptional`).  
3. Empty / missing `Company.domain` → FD-03 **UNKNOWN** `MISSING_INPUT:company_website`.  
4. DNS/timeout on website → **UNKNOWN** `WEBSITE_UNREACHABLE` (not FAIL).  
5. Unit tests use fixture HTML only; no live scrape in CI.  
6. Seeded CheckMaster: FD-03 `is_optional=True`.  
7. Scraper matches the example script in §4.2 as PASS.

---

## 11. Out of scope

- Headless browser / GTM-only delayed injection  
- Verifying `_smid` equals the connected Manago account id (nice follow-up)  
- Scraping every sitemap URL (homepage / `Company.domain` root only for MVP)  
- Reworking FD-07 API/VISIT logic (separate unless product merges later)  
- ERP feed checks (removed from FD-03 by this PRD)

---

## 12. Related PRDs

| Doc | Relation |
|-----|----------|
| Maheep AUTH-01 | Collects / stores `Company.domain` (`company_domain`) |
| Maheep FE-03 | FD-03 `isOptional=true` — optional FAIL does not block dashboard |
| DCS-02 | Foundation gate inventory — update FD-03 row |
| DCS-01 | Runs executor inside `run_dcs_score` |
| DCS-00 | Assemble ignores optional gate for BLOCKED when FE-03 rules apply |
