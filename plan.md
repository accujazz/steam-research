# Steam Genre Research Dashboard

## Recommended Plan

### Tech Stack

**Python + Streamlit** for the dashboard. It's the best fit here because:
- The heavy lifting (data fetching, revenue formula, quartile math) is Python anyway
- Streamlit lets you build a solid interactive UI without writing any frontend code
- Easy to run locally *or* deploy free on Streamlit Cloud in minutes
- No database needed — cache results as JSON/CSV files per genre research

---

### Architecture

```
[User Input]
  Tags (AND/OR logic)  OR  Manual App ID list
        ↓
[Discovery Layer]
  Steam tag name → ID lookup (populartags/english)
  Steam search API → candidate App IDs (paginated, 100/page)
  AND: fetch up to _AND_TAG_FETCH_LIMIT (500) per tag, then intersect
  OR:  fetch up to max_results per tag, then union
  No max_results cap here — applied after enrichment
        ↓
[Confirmation Modal]  (tag discovery only)
  Show discovered game count → Proceed / Cancel
  Three-step session state: pending_fetch → fetch_confirmed → fetch_running
        ↓
[Enrichment Layer]
  Per-app: Steam Store API → min_reviews filter → Steam Review API (total + 3 windows)
           → Community Group XML (followers)
  After enrichment: sort by total reviews desc, truncate to max_results
        ↓
[Calculation Layer]
  Revenue formula (coefficients: sales coeff, regional, Steam cut)
  Compute Q1/Q2/Q3 quartiles
        ↓
[Cache]
  Save as JSON file (genre_slug_YYYYMMDD.json) with timestamp
        ↓
[Streamlit Dashboard]
  Summary stats panel (quartile table)
  Games table (sortable, filterable)
  Charts: revenue distribution, price vs. reviews scatter
  Export to XLSX button
```

---

### Dashboard Screens

1. **Research setup** — enter tags or App IDs, set filter (min reviews, max games), configure coefficients
2. **Summary panel** — Q1/Q2/Q3 table for reviews, estimated revenue, wishlists
3. **Games table** — sortable by any column, with EA badge
4. **Charts** — revenue distribution histogram, scatter plot of price vs. reviews
5. **Export** — one-click XLSX download

---

### Key Implementation Notes

- **Rate limiting:** Steam search 0.5s between pages; Store API 1.5s per app; Review API 0.5s per window call.
- **Caching:** Timestamped JSON per run for historical comparisons.
- **Revenue formula** fully configurable in UI — sales coeff, regional coeff, Steam cut.
- **Wishlists** estimated as `followers × 10` using Steam Community group member count.

---

## File Structure

```
steam-research/
├── app.py           # Streamlit entry point and all UI
├── fetcher.py       # API clients, discovery, enrichment, caching
├── calculator.py    # Revenue formula, quartile math, derived fields
├── requirements.txt
└── cache/           # JSON snapshots (one file per research run)
```

---

## Data Sources

- **Steam Popular Tags** `store.steampowered.com/tagdata/populartags/english` — 446 tags, name → tagid mapping; fetched once and cached in memory
- **Steam Search API** `store.steampowered.com/search/results/?tags=<tagid>&json=1&start=<N>&count=100` — paginated app discovery; appid extracted from logo URL via regex
- **Steam Store API** `store.steampowered.com/api/appdetails?appids=<id>&cc=us&l=en` — release date, EA flag, current price, genres, `recommendations.total` (used for min_reviews filter)
- **Steam Review API** `store.steampowered.com/appreviews/<id>?json=1&language=all&num_per_page=0` — authoritative review counts; supports `start_date`/`end_date` Unix timestamp filtering for windowed counts
- **Steam Community Group XML** `steamcommunity.com/games/<id>/memberslistxml/?xml=1` — follower count extracted via regex `<memberCount>(\d+)</memberCount>` (avoids XML parse failures from unescaped `&` in game names)

---

## Core Data Structure

Every game is a flat `GameRecord` dict:

```python
{
  # Identity
  'appid': int, 'name': str,
  # Steam Store
  'positive': int, 'negative': int,       # from Steam Review API
  'steam_price': int,                      # cents, may be None
  'release_date': str,                     # "YYYY-MM-DD"
  'is_early_access': bool,
  'genres': list[str],
  'short_description': str,
  # Steam Community
  'followers': int,                        # group member count = followers
  # Steam Review API windowed counts (None if window hasn't elapsed yet)
  'reviews_30d': int | None,
  'reviews_1y': int | None,
  'reviews_3y': int | None,
  # Derived (added by calculator.py)
  'total_reviews': int,
  'review_score': float,                   # positive / total
  'wishlist_estimate': int,                # followers * wishlist_coeff (default 10)
  'price_usd': float,                      # steam_price / 100
  'revenue_estimate': float,               # total_reviews * price * coefficients
}
```

---

## `fetcher.py` — Key Functions

```python
def fetch_steam_tags() -> dict[str, int]
    # GET populartags/english → {name_lower: tagid}, cached in memory

def fetch_steam_search_apps(tag_id, max_results=None) -> dict[int, str]
    # Paginates Steam search (100/page), extracts appid from logo URL regex
    # Stops early if max_results reached

def fetch_steam_store(appid) -> dict | None
    # GET appdetails → parsed store data, None if not a game

def fetch_steam_reviews(appid, start_date=-1, end_date=-1) -> dict | None
    # Returns {"positive": int, "negative": int}
    # Pass start_date/end_date Unix timestamps for windowed counts

def fetch_steam_group_followers(appid) -> int | None
    # Regex-extracts <memberCount> from memberslistxml response
    # (avoids XML parser failure on unescaped & in game names)

def _reviews_in_window(appid, release_date_str, days) -> int | None
    # Returns None if window end date hasn't elapsed yet

def build_game_record(appid, name, store_data) -> GameRecord
    # Pure function, no SteamSpy dependency

def discover_apps(tags, logic: 'AND'|'OR', max_results=None) -> dict[int, str]
    # Looks up tag IDs, paginates Steam search, applies AND/OR logic
    # AND: fetches up to _AND_TAG_FETCH_LIMIT (500) per tag, then intersects
    # OR:  fetches up to max_results per tag, then unions
    # No final cap — caller truncates after enrichment sorted by reviews
    # Tags not in Steam's 446 popular tags are skipped with a warning

def enrich_apps(appids, names=None, progress_callback=None, store_delay=1.5, min_reviews=0)
    # Per app: Store API → min_reviews filter (recommendations.total) → Review API
    #          → followers → review windows (30d/1yr/3yr)

def save_cache(records, slug, cache_dir='cache') -> str
def load_cache(filepath) -> list[GameRecord]
def list_cache_files(cache_dir='cache') -> list[str]
```

---

## `calculator.py` — Key Functions

Defaults: `sales_coeff=0.7`, `regional_coeff=0.65`, `steam_cut=0.30`, `taxes=0.10`, `wishlist_coeff=13`, `reviews_multiplier=30`

```python
def compute_revenue(reviews, price_usd, reviews_multiplier, sales_coeff, regional_coeff, steam_cut, taxes) -> float | None
    # Returns None if reviews is None (window hasn't elapsed)
    # price_usd * reviews * reviews_multiplier * sales_coeff * regional_coeff * (1 - steam_cut) * (1 - taxes)

def enrich_records(records, wishlist_coeff, reviews_multiplier, sales_coeff, regional_coeff, steam_cut, taxes) -> list
    # Adds: total_reviews, review_score, price_usd (steam_price_initial / 100),
    #       wishlist_estimate = followers * wishlist_coeff
    #       revenue_total, revenue_30d, revenue_1y, revenue_3y  (None if reviews field is None)
    #       revenue_estimate = revenue_30d if available, else revenue_total (used for summary/charts)

def compute_quartiles(records, field='revenue_estimate') -> dict
def to_dataframe(records) -> pd.DataFrame
```

---

## `app.py` — Streamlit Layout

**Sidebar:**
- Top: **Previous Runs** — 10 most recent as buttons; older runs collapsed in expander. Clicking loads run and sets `?run=<filepath>` query param.
- Data source: mode (tag/manual). Tag mode: tags input, AND/OR logic (default AND), min reviews pre-filter (default 100), max games (default 50).
- Revenue coefficients: `reviews_multiplier` (default 30), `sales_coeff`, `regional_coeff`, `steam_cut` slider (default 30%), `taxes` slider (default 10%), `wishlist_coeff` (default 13).
- Fetch Data button.

Changing coefficients re-runs `enrich_records()` without re-fetching.

**Tag discovery confirmation modal:**
After discovery completes, a `@st.dialog` modal shows the count of discovered games and Proceed / Cancel buttons. Three-step session state machine:
1. `pending_fetch` only → show modal
2. `fetch_confirmed` set (Proceed clicked) → pop flag, set `fetch_running`, rerun (closes modal in a clean render cycle)
3. `fetch_running` set → run enrichment, show progress bar

After enrichment: records sorted by `positive + negative` (total reviews) descending, then truncated to `max_results`. Cancel clears `pending_fetch` and aborts.

**Main area header:** active run name displayed as `st.header` (h2) with a 🗑️ delete button — deletes the JSON file, clears session, returns to empty state.

**Games Table columns:** name, Steam Page link (`store.steampowered.com/app/<appid>/`, constructed at display time), reviews (total/30d/1yr/3yr), review score, price (initial/non-discounted), revenue (total/30d/1yr/3yr), wishlist est., followers, EA, release date, genres.
Revenue and review fields show empty when the time window hasn't elapsed.

**Charts:** revenue histogram (log scale + quartile lines), price vs reviews scatter (size=revenue, color=EA).

---

## `requirements.txt`

```
streamlit>=1.35.0
requests>=2.32.0
pandas>=2.2.0
numpy>=1.26.0
plotly>=5.22.0
openpyxl>=3.1.0
```

---

## Corrections vs. Initial Design

### SteamSpy replaced entirely for discovery and game details
Initial design used SteamSpy for tag→appid discovery and per-app details. Replaced with:
- Tag discovery: Steam Popular Tags API (name→ID) + Steam Search API (paginated, appid from logo URL)
- Per-app details: Steam Store API (already used), Steam Review API, Community Group XML
- Dropped fields that had no Steam equivalent: `tags` (user-voted), `average_forever`, `steamspy_price`
- `genres` (from Store API) replaces `tags` in the Games Table

### Review counts: Steam Review API, not SteamSpy
SteamSpy review data lags for newer games (returns 0 for games with thousands of real reviews). Steam Review API is always authoritative. Also supports windowed counts (first 30d/1yr/3yr from release) via `start_date`/`end_date` Unix timestamp params. Windows not yet elapsed return `None` (displayed as empty cells).

### Wishlists: followers × 10, not reviews × 12
Replaced `total_reviews × 12` with `followers × 10`, where followers = Steam Community group member count from `steamcommunity.com/games/<id>/memberslistxml/`. Follower count extracted via regex to avoid XML parse failures from unescaped `&` characters in some game names.

### Owners field removed
SteamSpy owner estimates were too inaccurate. Field dropped entirely. Revenue formula uses `total_reviews` as the base multiplier.

### Revenue formula
`revenue = price × reviews × reviews_multiplier × sales_coeff × regional_coeff × (1 − steam_cut) × (1 − taxes)`
Four revenue fields: `revenue_total`, `revenue_30d`, `revenue_1y`, `revenue_3y` — each `None` when the corresponding reviews window hasn't elapsed.
`revenue_estimate` (used for summary/charts) = `revenue_30d` if available, else `revenue_total`.
Defaults: `sales_coeff=0.7`, `regional_coeff=0.65`, `steam_cut=0.30`, `taxes=0.10`.
Price uses `price_overview.initial` (non-discounted) from Steam Store API.

### Tag discovery pre-filtering
`min_reviews` (default 100) applied in `enrich_apps` after `fetch_steam_store` using `recommendations.total` — skips expensive Review API + followers + window calls for low-review games.

### max_results cap moved to post-enrichment
Previously `max_results` was applied inside `discover_apps` (per-tag for AND), which caused incomplete AND intersections — games with both tags but ranked below `max_results` in either tag's search results were silently dropped. Now:
- AND: each tag fetches up to `_AND_TAG_FETCH_LIMIT = 500` (fetcher.py constant), intersection computed from full sets
- OR: each tag still capped at `max_results` during search (union of top-N per tag)
- Final truncation happens after `enrich_apps`: records sorted by `positive + negative` descending, then `records[:max_results]`
- Result: `max_results` returns the most-reviewed games from the full intersection/union, not an arbitrary slice
