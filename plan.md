# Steam Genre Research Dashboard

## Recommended Plan

### Tech Stack

**Python + Streamlit** for the dashboard. It's the best fit here because:
- The heavy lifting (data fetching, revenue formula, quartile math) is Python anyway
- Streamlit lets you build a solid interactive UI without writing any frontend code
- Easy to run locally *or* deploy free on Streamlit Cloud in minutes
- No database needed — cache results as JSON/CSV files per genre research

**Data sources:**
- **SteamSpy API** (`steamspy.com/api.php`) — free, no key, returns reviews, owners, tags, price per app. The main workhorse.
- **Steam Store API** (`store.steampowered.com/api/appdetails`) — for release date, EA status, current price, official tags
- **Steam Search/Tag pages** — for discovering App IDs by tag combination (scraping or using SteamSpy's tag endpoint)

---

### Architecture

```
[User Input]
  Tags (AND/OR logic)  OR  Manual App ID list
        ↓
[Discovery Layer]
  SteamSpy tag endpoint → candidate App IDs
        ↓
[Enrichment Layer]
  Per-app: SteamSpy details + Steam Store API + Steam Review API + Community Group XML
  → reviews (30d/1yr/3yr/total), price, release date, EA flag, followers
        ↓
[Calculation Layer]
  Apply revenue formula (coefficients: sales coeff, regional, Steam cut)
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

1. **Research setup** — enter tags or App IDs, set filter (min reviews, min price), configure coefficients
2. **Summary panel** — Q1/Q2/Q3 table for reviews, estimated revenue, wishlists
3. **Games table** — sortable by any column, with EA badge
4. **Charts** — revenue distribution histogram, scatter plot of price vs. reviews
5. **Export** — one-click XLSX download

---

### Key Implementation Notes

- **Rate limiting:** SteamSpy ~1 req/sec; Steam Store API stricter — add delays. Review API windowed calls use 0.5s delay.
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

- **SteamSpy API** `steamspy.com/api.php` — tag discovery, price, tags, avg playtime
  - Tag discovery: `?request=tag&tag=<tagname>` → all appids with that tag
  - App details: `?request=appdetails&appid=<id>`
- **Steam Store API** `store.steampowered.com/api/appdetails?appids=<id>&cc=us&l=en` — release date, EA flag, current price
- **Steam Review API** `store.steampowered.com/appreviews/<id>?json=1&language=all&num_per_page=0` — authoritative review counts; supports `start_date`/`end_date` Unix timestamp filtering for windowed counts
- **Steam Community Group XML** `steamcommunity.com/games/<id>/memberslistxml/?xml=1` — follower count (`<memberCount>` in `<groupDetails>`)

---

## Core Data Structure

Every game is a flat `GameRecord` dict:

```python
{
  # Identity
  'appid': int, 'name': str,
  # SteamSpy
  'positive': int, 'negative': int,       # overwritten by Steam Review API
  'average_forever': int,                  # avg playtime (minutes)
  'steamspy_price': int,                   # cents
  'tags': dict[str, int],                  # tag → vote count
  # Steam Store
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
  'price_usd': float,                      # steam_price/100, fallback steamspy_price/100
  'revenue_estimate': float,               # total_reviews * price * coefficients
}
```

---

## `fetcher.py` — Key Functions

```python
def fetch_tag_apps(tag: str) -> dict[int, str]
def fetch_steamspy_details(appid: int) -> dict
def fetch_steam_store(appid: int) -> dict | None
def fetch_steam_reviews(appid, start_date=-1, end_date=-1) -> dict | None
    # Returns {"positive": int, "negative": int}
    # Pass start_date/end_date Unix timestamps for windowed counts
def fetch_steam_group_followers(appid: int) -> int | None
def _reviews_in_window(appid, release_date_str, days) -> int | None
    # Returns None if window end date hasn't elapsed yet
def build_game_record(appid, spy_data, store_data) -> GameRecord
def discover_apps(tags, logic: 'AND'|'OR') -> dict[int, str]
def enrich_apps(appids, progress_callback, spy_delay, store_delay) -> list[GameRecord]
    # Per app: SteamSpy → Store API → Steam Review API (total + 3 windows)
    #          → Community Group XML (followers)
def save_cache(records, slug, cache_dir='cache') -> str
def load_cache(filepath) -> list[GameRecord]
def list_cache_files(cache_dir='cache') -> list[str]
```

---

## `calculator.py` — Key Functions

Defaults: `sales_coeff=0.7`, `regional_coeff=0.65`, `steam_cut=0.30`, `wishlist_coeff=10`

```python
def compute_revenue(total_reviews, price_usd, sales_coeff, regional_coeff, steam_cut) -> float
    # total_reviews * price_usd * sales_coeff * regional_coeff * (1 - steam_cut)

def enrich_records(records, wishlist_coeff, sales_coeff, regional_coeff, steam_cut) -> list
    # Adds: total_reviews, review_score, price_usd,
    #       wishlist_estimate = followers * wishlist_coeff
    #       revenue_estimate = compute_revenue(total_reviews, ...)

def compute_quartiles(records, field='revenue_estimate') -> dict
def to_dataframe(records) -> pd.DataFrame
```

---

## `app.py` — Streamlit Layout

**Sidebar:** mode (tag/manual), revenue coefficients, wishlist/follower ratio, cache load, Fetch button.
Changing coefficients re-runs `enrich_records()` without re-fetching.

**Games Table columns:** name, reviews (total/30d/1yr/3yr), review score, price, revenue est., wishlist est., followers, EA, release date, tags.
Reviews (1yr/3yr) show empty if window hasn't elapsed.

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

### Review counts: Steam Review API, not SteamSpy
SteamSpy review data lags for newer games (returns 0 for games with thousands of real reviews). Steam Review API is always authoritative. Also supports windowed counts (first 30d/1yr/3yr from release) via `start_date`/`end_date` Unix timestamp params. Windows not yet elapsed return `None` (displayed as empty cells).

### Wishlists: followers × 10, not reviews × 12
Replaced `total_reviews × 12` with `followers × 10`, where followers = Steam Community group member count from `steamcommunity.com/games/<id>/memberslistxml/`.

### Owners field removed
SteamSpy owner estimates (extrapolated from review counts) were too inaccurate to be useful. Field dropped entirely. Revenue formula now uses `total_reviews` as the base multiplier instead of `owners_midpoint`.

### Revenue formula base: total_reviews, not owners
`revenue_estimate = total_reviews × price × sales_coeff × regional_coeff × (1 − steam_cut)`
Default coefficients: `sales_coeff=0.7`, `regional_coeff=0.65`.
