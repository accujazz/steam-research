import json
import logging
import os
import re
import time
from datetime import date
from typing import Callable, Dict, List, Literal, Optional, Tuple, TypedDict

import requests

logger = logging.getLogger(__name__)

STEAMSPY_URL = "https://steamspy.com/api.php"
STEAM_STORE_URL = "https://store.steampowered.com/api/appdetails"
STEAM_REVIEWS_URL = "https://store.steampowered.com/appreviews"
STEAM_GROUP_URL = "https://steamcommunity.com/games"


class GameRecord(TypedDict, total=False):
    appid: int
    name: str
    positive: int
    negative: int
    average_forever: int
    steamspy_price: int
    tags: Dict
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


def parse_owners(owners_str: str) -> Tuple[int, int]:
    nums = re.findall(r"[\d,]+", owners_str)
    if len(nums) < 2:
        return (0, 0)
    low = int(nums[0].replace(",", ""))
    high = int(nums[1].replace(",", ""))
    return (low, high)


def build_game_record(appid: int, spy_data: dict, store_data: Optional[dict]) -> GameRecord:
    steamspy_price_raw = spy_data.get("price", 0)
    try:
        steamspy_price = int(steamspy_price_raw)
    except (TypeError, ValueError):
        steamspy_price = 0

    record: GameRecord = {
        "appid": appid,
        "name": spy_data.get("name", ""),
        "positive": int(spy_data.get("positive", 0) or 0),
        "negative": int(spy_data.get("negative", 0) or 0),
        "average_forever": int(spy_data.get("average_forever", 0) or 0),
        "steamspy_price": steamspy_price,
        "tags": spy_data.get("tags") or {},
        "steam_price": None,
        "release_date": None,
        "is_early_access": False,
        "genres": [],
        "short_description": "",
    }

    if store_data:
        price_overview = store_data.get("price_overview") or {}
        record["steam_price"] = price_overview.get("final")

        release = store_data.get("release_date") or {}
        raw_date = release.get("date", "")
        record["release_date"] = _parse_release_date(raw_date)

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


def fetch_tag_apps(tag: str) -> Dict[int, str]:
    resp = requests.get(STEAMSPY_URL, params={"request": "tag", "tag": tag}, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    return {int(appid): info.get("name", "") for appid, info in data.items()}


def fetch_steamspy_details(appid: int) -> dict:
    resp = requests.get(STEAMSPY_URL, params={"request": "appdetails", "appid": appid}, timeout=15)
    resp.raise_for_status()
    return resp.json()


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
        import xml.etree.ElementTree as ET
        resp = requests.get(
            f"{STEAM_GROUP_URL}/{appid}/memberslistxml/",
            params={"xml": "1"},
            timeout=15,
        )
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
        count = root.findtext("groupDetails/memberCount")
        return int(count) if count else None
    except Exception as e:
        logger.warning("Steam group followers failed for appid %d: %s", appid, e)
        return None


def discover_apps(tags: List[str], logic: Literal["AND", "OR"] = "OR") -> Dict[int, str]:
    results: List[Dict[int, str]] = []
    for tag in tags:
        try:
            apps = fetch_tag_apps(tag.strip())
            results.append(apps)
            time.sleep(1.0)
        except Exception as e:
            logger.warning("Failed to fetch tag '%s': %s", tag, e)

    if not results:
        return {}

    if logic == "AND":
        common_ids = set(results[0].keys())
        for r in results[1:]:
            common_ids &= set(r.keys())
        merged: Dict[int, str] = {}
        for appid in common_ids:
            for r in results:
                if appid in r:
                    merged[appid] = r[appid]
                    break
        return merged
    else:
        merged = {}
        for r in results:
            merged.update(r)
        return merged


def enrich_apps(
    appids: List[int],
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    spy_delay: float = 1.0,
    store_delay: float = 1.5,
) -> List[GameRecord]:
    records: List[GameRecord] = []
    total = len(appids)

    for i, appid in enumerate(appids):
        try:
            time.sleep(spy_delay)
            spy_data = fetch_steamspy_details(appid)
            name = spy_data.get("name", str(appid))

            if progress_callback:
                progress_callback(i + 1, total, name)

            time.sleep(store_delay)
            store_data = fetch_steam_store(appid)

            record = build_game_record(appid, spy_data, store_data)

            # Always use Steam Review API for review counts — SteamSpy lags on newer games.
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
