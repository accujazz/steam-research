import json
import logging
import os
import re
import time
from datetime import date
from typing import Callable, Dict, List, Literal, Optional, Tuple, TypedDict

import requests

logger = logging.getLogger(__name__)

STEAM_STORE_URL = "https://store.steampowered.com/api/appdetails"
STEAM_REVIEWS_URL = "https://store.steampowered.com/appreviews"
STEAM_GROUP_URL = "https://steamcommunity.com/games"
STEAM_TAGS_URL = "https://store.steampowered.com/tagdata/populartags/english"
STEAM_SEARCH_URL = "https://store.steampowered.com/search/results/"

_tag_cache: Optional[Dict[str, int]] = None  # name_lower -> tagid


class GameRecord(TypedDict, total=False):
    appid: int
    name: str
    positive: int
    negative: int
    steam_price: Optional[int]
    release_date: Optional[str]
    is_early_access: bool
    genres: List
    short_description: str
    followers: Optional[int]
    reviews_30d: Optional[int]
    reviews_1y: Optional[int]
    reviews_3y: Optional[int]
    total_reviews: int
    review_score: float
    wishlist_estimate: int
    price_usd: float
    revenue_estimate: float


def fetch_steam_tags() -> Dict[str, int]:
    """Returns {tag_name_lower: tagid} for all Steam popular tags."""
    global _tag_cache
    if _tag_cache is not None:
        return _tag_cache
    resp = requests.get(STEAM_TAGS_URL, timeout=15)
    resp.raise_for_status()
    _tag_cache = {t["name"].lower(): t["tagid"] for t in resp.json()}
    return _tag_cache


def fetch_steam_search_apps(tag_id: int, max_results: Optional[int] = None) -> Dict[int, str]:
    """Returns {appid: name} by paginating Steam search for a tag ID."""
    appid_re = re.compile(r"/apps/(\d+)/")
    result: Dict[int, str] = {}
    start = 0
    while True:
        resp = requests.get(
            STEAM_SEARCH_URL,
            params={"tags": tag_id, "json": 1, "start": start, "count": 100},
            timeout=15,
        )
        resp.raise_for_status()
        items = resp.json().get("items", [])
        if not items:
            break
        for item in items:
            m = appid_re.search(item.get("logo", ""))
            if m:
                appid = int(m.group(1))
                result[appid] = item.get("name", "")
        if max_results and len(result) >= max_results:
            break
        if len(items) < 100:
            break
        start += 100
        time.sleep(0.5)

    if max_results:
        result = dict(list(result.items())[:max_results])
    return result


def build_game_record(appid: int, name: str, store_data: Optional[dict]) -> GameRecord:
    record: GameRecord = {
        "appid": appid,
        "name": name,
        "positive": 0,
        "negative": 0,
        "steam_price": None,
        "release_date": None,
        "is_early_access": False,
        "genres": [],
        "short_description": "",
    }

    if store_data:
        record["name"] = store_data.get("name", name)

        price_overview = store_data.get("price_overview") or {}
        record["steam_price"] = price_overview.get("final")

        release = store_data.get("release_date") or {}
        record["release_date"] = _parse_release_date(release.get("date", ""))

        genres = store_data.get("genres") or []
        record["genres"] = [g.get("description", "") for g in genres]
        record["is_early_access"] = any(
            g.get("description", "") == "Early Access" for g in genres
        )

        record["short_description"] = store_data.get("short_description", "")

    return record


def _parse_release_date(raw: str) -> Optional[str]:
    if not raw:
        return None
    for fmt in ("%b %d, %Y", "%d %b, %Y", "%B %d, %Y", "%Y-%m-%d"):
        try:
            from datetime import datetime
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return raw


def fetch_steam_store(appid: int) -> Optional[dict]:
    try:
        resp = requests.get(
            STEAM_STORE_URL,
            params={"appids": appid, "cc": "us", "l": "en"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        app_data = data.get(str(appid), {})
        if not app_data.get("success"):
            return None
        app_info = app_data.get("data", {})
        if app_info.get("type") != "game":
            return None
        return app_info
    except requests.exceptions.RequestException as e:
        logger.warning("Steam Store API failed for appid %d: %s", appid, e)
        return None


def fetch_steam_reviews(appid: int, start_date: int = -1, end_date: int = -1) -> Optional[Dict]:
    """Returns {"positive": int, "negative": int} for the given date window (Unix timestamps).
    Pass start_date=-1, end_date=-1 for all-time totals."""
    try:
        params = {"json": "1", "language": "all", "num_per_page": 0, "filter": "all"}
        if start_date != -1 and end_date != -1:
            params["start_date"] = start_date
            params["end_date"] = end_date
            params["date_range_type"] = "include"
        resp = requests.get(f"{STEAM_REVIEWS_URL}/{appid}", params=params, timeout=15)
        resp.raise_for_status()
        summary = resp.json().get("query_summary", {})
        return {
            "positive": int(summary.get("total_positive", 0) or 0),
            "negative": int(summary.get("total_negative", 0) or 0),
        }
    except Exception as e:
        logger.warning("Steam Review API failed for appid %d: %s", appid, e)
        return None


def _reviews_in_window(appid: int, release_date_str: Optional[str], days: int) -> Optional[int]:
    """Fetch review count for the first `days` days after release.
    Returns None if the window hasn't fully elapsed yet."""
    if not release_date_str:
        return None
    try:
        from datetime import datetime, timedelta
        release_dt = datetime.strptime(release_date_str, "%Y-%m-%d")
        end_dt = release_dt + timedelta(days=days)
        if end_dt > datetime.utcnow():
            return None
        start_ts = int(release_dt.timestamp())
        end_ts = int(end_dt.timestamp())
        time.sleep(0.5)
        data = fetch_steam_reviews(appid, start_date=start_ts, end_date=end_ts)
        if data:
            return data["positive"] + data["negative"]
    except Exception as e:
        logger.warning("Review window fetch failed for appid %d days=%d: %s", appid, days, e)
    return None


def fetch_steam_group_followers(appid: int) -> Optional[int]:
    try:
        resp = requests.get(
            f"{STEAM_GROUP_URL}/{appid}/memberslistxml/",
            params={"xml": "1"},
            timeout=15,
        )
        resp.raise_for_status()
        m = re.search(r"<memberCount>(\d+)</memberCount>", resp.text)
        return int(m.group(1)) if m else None
    except Exception as e:
        logger.warning("Steam group followers failed for appid %d: %s", appid, e)
        return None


def discover_apps(
    tags: List[str],
    logic: Literal["AND", "OR"] = "OR",
    max_results: Optional[int] = None,
) -> Dict[int, str]:
    """Discover app IDs via Steam search. AND = intersection, OR = union.
    max_results caps total returned (no pre-filtering by reviews — done in enrich_apps)."""
    tag_map = fetch_steam_tags()
    per_tag_results: List[Dict[int, str]] = []

    for tag in tags:
        tag_id = tag_map.get(tag.strip().lower())
        if tag_id is None:
            logger.warning("Tag not found in Steam tag list: '%s'", tag)
            continue
        try:
            apps = fetch_steam_search_apps(tag_id, max_results=max_results)
            per_tag_results.append(apps)
            time.sleep(1.0)
        except Exception as e:
            logger.warning("Failed to fetch tag '%s': %s", tag, e)

    if not per_tag_results:
        return {}

    if logic == "AND":
        common_ids = set(per_tag_results[0].keys())
        for r in per_tag_results[1:]:
            common_ids &= set(r.keys())
        merged = {appid: per_tag_results[0][appid] for appid in common_ids if appid in per_tag_results[0]}
    else:
        merged: Dict[int, str] = {}
        for r in per_tag_results:
            merged.update(r)

    if max_results and len(merged) > max_results:
        merged = dict(list(merged.items())[:max_results])

    return merged


def enrich_apps(
    appids: List[int],
    names: Optional[Dict[int, str]] = None,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    store_delay: float = 1.5,
    min_reviews: int = 0,
) -> List[GameRecord]:
    records: List[GameRecord] = []
    total = len(appids)
    names = names or {}

    for i, appid in enumerate(appids):
        try:
            name = names.get(appid, str(appid))

            if progress_callback:
                progress_callback(i + 1, total, name)

            time.sleep(store_delay)
            store_data = fetch_steam_store(appid)

            # Apply min_reviews filter using recommendations.total from store API
            if min_reviews > 0 and store_data:
                total_recs = (store_data.get("recommendations") or {}).get("total", 0) or 0
                if total_recs < min_reviews:
                    logger.debug("Skipping appid %d (%s): %d reviews < %d", appid, name, total_recs, min_reviews)
                    continue

            record = build_game_record(appid, name, store_data)

            review_data = fetch_steam_reviews(appid)
            if review_data:
                record["positive"] = review_data["positive"]
                record["negative"] = review_data["negative"]

            record["followers"] = fetch_steam_group_followers(appid)

            release_date = record.get("release_date")
            record["reviews_30d"] = _reviews_in_window(appid, release_date, 30)
            record["reviews_1y"]  = _reviews_in_window(appid, release_date, 365)
            record["reviews_3y"]  = _reviews_in_window(appid, release_date, 1095)

            records.append(record)
        except Exception as e:
            logger.warning("Skipping appid %d: %s", appid, e)

    return records


def save_cache(records: List[GameRecord], slug: str, cache_dir: str = "cache") -> str:
    os.makedirs(cache_dir, exist_ok=True)
    today = date.today().strftime("%Y%m%d")
    filename = f"{slug}_{today}.json"
    filepath = os.path.join(cache_dir, filename)
    payload = {
        "meta": {"slug": slug, "date": today, "count": len(records)},
        "games": records,
    }
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return filepath


def load_cache(filepath: str) -> List[GameRecord]:
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data["games"]


def list_cache_files(cache_dir: str = "cache") -> List[str]:
    if not os.path.isdir(cache_dir):
        return []
    files = [
        os.path.join(cache_dir, f)
        for f in os.listdir(cache_dir)
        if f.endswith(".json")
    ]
    return sorted(files, reverse=True)
