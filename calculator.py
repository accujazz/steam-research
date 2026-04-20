import pandas as pd
import numpy as np

DEFAULT_SALES_COEFF = 0.7
DEFAULT_REGIONAL_COEFF = 0.65
DEFAULT_STEAM_CUT = 0.30
DEFAULT_TAXES = 0.10
DEFAULT_WISHLIST_COEFF = 13


def compute_revenue(
    total_reviews: int,
    price_usd: float,
    sales_coeff: float = DEFAULT_SALES_COEFF,
    regional_coeff: float = DEFAULT_REGIONAL_COEFF,
    steam_cut: float = DEFAULT_STEAM_CUT,
    taxes: float = DEFAULT_TAXES,
) -> float:
    return price_usd * total_reviews * 30 * sales_coeff * regional_coeff * (1 - steam_cut) * (1 - taxes)


def enrich_records(
    records: list,
    wishlist_coeff: int = DEFAULT_WISHLIST_COEFF,
    sales_coeff: float = DEFAULT_SALES_COEFF,
    regional_coeff: float = DEFAULT_REGIONAL_COEFF,
    steam_cut: float = DEFAULT_STEAM_CUT,
    taxes: float = DEFAULT_TAXES,
) -> list:
    enriched = []
    for r in records:
        rec = dict(r)
        positive = rec.get("positive", 0) or 0
        negative = rec.get("negative", 0) or 0
        total = positive + negative
        rec["total_reviews"] = total
        rec["review_score"] = (positive / total) if total > 0 else 0.0
        followers = rec.get("followers") or 0
        rec["wishlist_estimate"] = followers * wishlist_coeff

        steam_price = rec.get("steam_price")
        price_usd = (steam_price / 100) if steam_price else 0.0
        rec["price_usd"] = price_usd

        reviews_for_revenue = rec.get("reviews_30d") if rec.get("reviews_30d") is not None else rec.get("total_reviews", 0)
        rec["revenue_estimate"] = compute_revenue(
            reviews_for_revenue or 0,
            rec.get("price_usd", 0) or 0,
            sales_coeff,
            regional_coeff,
            steam_cut,
            taxes,
        )
        enriched.append(rec)
    return enriched


def compute_quartiles(records: list, field: str = "revenue_estimate") -> dict:
    values = [r.get(field, 0) or 0 for r in records if r.get(field) is not None]
    if not values:
        return {"min": 0, "Q1": 0, "median": 0, "Q3": 0, "max": 0, "mean": 0}
    arr = np.array(values, dtype=float)
    return {
        "min": float(np.min(arr)),
        "Q1": float(np.percentile(arr, 25)),
        "median": float(np.median(arr)),
        "Q3": float(np.percentile(arr, 75)),
        "max": float(np.max(arr)),
        "mean": float(np.mean(arr)),
    }


def to_dataframe(records: list) -> pd.DataFrame:
    if not records:
        return pd.DataFrame()
    df = pd.DataFrame(records)
    df = df.set_index("appid")

    if "release_date" in df.columns:
        df["release_date"] = pd.to_datetime(df["release_date"], errors="coerce")

    if "genres" in df.columns:
        df["genres"] = df["genres"].apply(
            lambda g: ", ".join(g) if isinstance(g, list) else ""
        )

    return df
