# Steam Genre Research Dashboard

## Recommended Plan

Given your answers, here's what I'd recommend and why:

---

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
  Per-app: SteamSpy details + Steam Store API
  → reviews, price, release date, EA flag, followers
        ↓
[Calculation Layer]
  Apply revenue formula (your coefficients: sales coeff, regional, Steam cut)
  Compute Q1/Q2/Q3 quartiles
        ↓
[Cache]
  Save as JSON file (genre_slug.json) with timestamp
        ↓
[Streamlit Dashboard]
  Summary stats panel (quartile table like your sheet)
  Games table (sortable, filterable)
  Charts: revenue distribution, review velocity, price vs. reviews scatter
  Export to XLSX button (replicates your current format)
```

---

### Dashboard Screens

1. **Research setup** — enter tags or App IDs, set filter (min reviews, min price), configure coefficients (you may want to tweak the 0.65 regional factor per genre)
2. **Summary panel** — Q1/Q2/Q3 table for reviews, estimated revenue, wishlists (mirrors your header rows)
3. **Games table** — sortable by any column, with EA badge, links to Steam pages
4. **Charts** — revenue distribution histogram, scatter plot of price vs. reviews, 30-day review velocity bar chart
5. **Export** — one-click XLSX download matching your current sheet format

---

### Key Implementation Notes

- **Rate limiting:** SteamSpy allows ~1 req/sec; for a genre of ~30–50 games that's under a minute. Steam Store API is stricter — add a small delay.
- **Caching:** Save each research run as a timestamped JSON so you can compare the same genre over time (e.g. quarterly snapshots — which is what your 30-day/1-year/3-year columns suggest you're already doing manually).
- **Revenue formula** is fully configurable in the UI — median price, sales coefficient, regional coefficient, and platform cut — so you can adjust without touching code.
- **Wishlists** are estimated (Steam doesn't expose this publicly), so the `reviews × ~12` multiplier your sheet uses stays as-is.

---

### What I'd build first (MVP order)

1. Data fetcher script (tags → App IDs → enriched data)
2. Revenue formula + quartile calculator
3. Streamlit table + summary panel
4. XLSX export
5. Charts
6. UI polish + caching layer

---

Ready to start implementing? Or do you have questions about any part of the plan first — e.g. whether SteamSpy has the coverage you need for your genres, or how to handle the discount tracking sheet (Sheet 3)?


## Context
Replace manual Steam market research spreadsheets with a Streamlit dashboard that fetches from SteamSpy + Steam APIs, computes estimated revenue using a configurable formula, and exports to XLSX.

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

- **SteamSpy API** `steamspy.com/api.php` — no key, returns owners range, tags, price
  - Tag discovery: `?request=tag&tag=<tagname>` → all appids with that tag
  - App details: `?request=appdetails&appid=<id>`
- **Steam Store API** `store.steampowered.com/api/appdetails?appids=<id>&cc=us&l=en` — release date, EA flag, current price
- **Steam Review API** `store.steampowered.com/appreviews/<id>?json=1&language=all&num_per_page=0` — authoritative review counts (replaces SteamSpy reviews, which lag for newer games)
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
  'owners_low': int, 'owners_high': int, 'owners_midpoint': int,
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
  # Derived (added by calculator.py)
  'total_reviews': int,
  'review_score': float,
  'wishlist_estimate': int,                # followers * wishlist_coeff (default 10)
  'price_usd': float,                      # steam_price/100, fallback steamspy_price/100
  'revenue_estimate': float,
}
```

---

## `fetcher.py` — Key Functions

```python
def fetch_tag_apps(tag: str) -> dict[int, str]
    # GET steamspy tag endpoint → {appid: name}

def fetch_steamspy_details(appid: int) -> dict
    # GET steamspy appdetails endpoint → raw JSON

def fetch_steam_store(appid: int) -> dict | None
    # GET store API → parsed fields dict, or None if not found/not a game

def fetch_steam_reviews(appid: int) -> dict | None
    # GET Steam Review API → {"positive": int, "negative": int}
    # Always used in preference to SteamSpy review counts

def fetch_steam_group_followers(appid: int) -> int | None
    # GET steamcommunity.com/games/<appid>/memberslistxml/?xml=1
    # Parses <memberCount> from <groupDetails> — equals game's follower count

def parse_owners(owners_str: str) -> tuple[int, int]
    # "2,000,000 .. 5,000,000" → (2000000, 5000000), pure function

def build_game_record(appid: int, spy_data: dict, store_data: dict | None) -> GameRecord
    # Merges SteamSpy + Store API into normalized GameRecord, pure function

def discover_apps(tags: list[str], logic: Literal['AND', 'OR']) -> dict[int, str]
    # Calls fetch_tag_apps per tag, returns union (OR) or intersection (AND)

def enrich_apps(
    appids: list[int],
    progress_callback: Callable | None = None,
    spy_delay: float = 1.0,
    store_delay: float = 1.5,
) -> list[GameRecord]
    # Per app: SteamSpy → Store API → overwrite reviews from Steam Review API
    #          → fetch followers from Community Group XML
    # Per-app errors logged and skipped, never abort full run

def save_cache(records, slug, cache_dir='cache') -> str
    # Writes cache/<slug>_YYYYMMDD.json, returns filepath

def load_cache(filepath: str) -> list[GameRecord]
def list_cache_files(cache_dir='cache') -> list[str]
```

---

## `calculator.py` — Key Functions

Defaults: `sales_coeff=1.0`, `regional_coeff=1.3`, `steam_cut=0.30`, `wishlist_coeff=10`

```python
def compute_revenue(owners_midpoint, price_usd, sales_coeff, regional_coeff, steam_cut) -> float
    # owners_midpoint * price_usd * sales_coeff * regional_coeff * (1 - steam_cut)
    # Returns 0.0 if price_usd is 0 or None

def enrich_records(records, wishlist_coeff, sales_coeff, regional_coeff, steam_cut) -> list[GameRecord]
    # Adds derived fields: total_reviews, review_score, price_usd,
    #   wishlist_estimate = followers * wishlist_coeff
    #   revenue_estimate = compute_revenue(...)
    # Returns new list, does not mutate input

def compute_quartiles(records, field='revenue_estimate') -> dict[str, float]
    # Returns {"min", "Q1", "median", "Q3", "max", "mean"}

def to_dataframe(records) -> pd.DataFrame
    # Flat dict list → DataFrame, appid as index, dates as Timestamp
```

---

## `app.py` — Streamlit Layout

**Session state:** `records` (raw list), `enriched_df` (DataFrame)

**Sidebar:**
- Mode: "Tag Discovery" (tags + AND/OR) or "Manual App IDs"
- Revenue coefficients: `sales_coeff`, `regional_coeff`, `steam_cut`, `wishlist_coeff` (labeled "Wishlist / follower ratio")
- Cache load dropdown + Load button
- "Fetch Data" primary button

**Changing coefficients re-runs `enrich_records()` on cached `records` without re-fetching.**

**Main area — 3 tabs:**
1. **Summary** — metrics (count, median/Q1/Q3 revenue) + quartile table across revenue/reviews/price
2. **Games Table** — filters (price range, min reviews, EA toggle); sortable `st.dataframe` with formatted columns (Revenue Est., Score progress bar, Followers, Wishlists Est.); XLSX export
3. **Charts** — revenue histogram (log scale + quartile lines), price vs reviews scatter, owners vs revenue scatter

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

## Implementation Order

1. `fetcher.py`: `parse_owners()`, `build_game_record()` — pure functions
2. `fetcher.py`: `fetch_tag_apps()`, `fetch_steamspy_details()`, `fetch_steam_store()`
3. `fetcher.py`: `fetch_steam_reviews()`, `fetch_steam_group_followers()`
4. `fetcher.py`: `enrich_apps()` — full pipeline with all four API calls per app
5. `fetcher.py`: `save_cache()` / `load_cache()` round-trip
6. `calculator.py`: full module
7. `app.py`: sidebar + fetch → end-to-end pipeline verification
8. `app.py`: Games Table tab + XLSX export
9. `app.py`: Summary tab + Charts tab
10. `app.py`: cache load/save UI + `discover_apps()` AND/OR mode

---

## Corrections vs. Initial Design

### Review counts: Steam Review API, not SteamSpy
SteamSpy review data lags significantly for newer and smaller games (returns 0 for games with thousands of real reviews). The Steam Review API (`store.steampowered.com/appreviews/<id>`) is always authoritative. SteamSpy reviews are fetched but immediately overwritten by the Steam Review API result in `enrich_apps`.

### Wishlists: followers × 10, not reviews × 12
Initial plan estimated wishlists as `total_reviews × 12`. Replaced with `followers × 10`, where followers = Steam Community group member count fetched from `steamcommunity.com/games/<id>/memberslistxml/`. This is a more direct signal — group membership directly represents people tracking the game.
