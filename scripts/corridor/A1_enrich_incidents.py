"""
A1_enrich_incidents.py
======================
Task A1 — Enrich incident dataset with multivariate hazard attributes
and produce enriched metrics CSV files for both 5km and 10km windows.

WHAT THIS SCRIPT DOES
---------------------
1. Loads the raw PHMSA incident Excel file
2. Filters to the target state (Texas by default)
3. Computes a composite HAZARD SCORE per incident using 4 components:
      a) Consequence severity  (fatalities + injuries + normalised cost)
      b) Cause type weight     (corrosion / excavation damage ranked highest)
      c) Asset vulnerability   (pipe age proxy + diameter)
      d) Incident frequency    (each incident = 1 base count)
4. Re-reads the corridor windows GeoPackage files (windows_5km.gpkg /
   windows_10km.gpkg) and spatially joins enriched incidents to windows
5. Aggregates per-window:
      - incident_count         (same as before)
      - exposure_count         (same as before — segments per window)
      - risk_obs               (NEW: sum of hazard scores / exposure_count)
      - mean_severity          (mean consequence sub-score)
      - mean_cause_weight      (mean cause sub-score)
      - mean_vulnerability     (mean vulnerability sub-score)
6. Saves enriched metrics as:
      metrics_5km_enriched.csv
      metrics_10km_enriched.csv

These replace the original metrics_*km.csv files as inputs to
04_stats_and_bands.py.

HOW TO USE
----------
Step 1 — Place this file in your project scripts folder:
    C:\\projects\\icvars-metaverse-pipeline-risk\\scripts\\corridor\\

Step 2 — Open a terminal in your project root:
    cd C:\\projects\\icvars-metaverse-pipeline-risk

Step 3 — Run:
    python scripts/corridor/A1_enrich_incidents.py

Step 4 — Check the output. You will see printed summaries showing:
    - How many incidents were enriched
    - Score distribution across windows
    - How many windows now have risk_obs > 0

Step 5 — The script writes two files into:
    data/regions/us_tx/results_corridor/
        metrics_5km_enriched.csv
        metrics_10km_enriched.csv

Step 6 — Before running 04_stats_and_bands.py, update the CASES paths
    in that script to point to the enriched files:
        ("10km", ..., "metrics_10km_enriched.csv")
        ("5km",  ..., "metrics_5km_enriched.csv")

REQUIREMENTS
------------
    pip install geopandas pandas numpy openpyxl shapely
"""

from __future__ import annotations

import os
import sys
import warnings
import numpy as np
import pandas as pd
import geopandas as gpd

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)

# ─────────────────────────────────────────────
# CONFIGURATION — edit paths here if needed
# ─────────────────────────────────────────────

ROOT = r"C:\projects\icvars-metaverse-pipeline-risk"

INCIDENT_XLSX = os.path.join(ROOT, "data", "raw", "gtggungs2010toPresent.xlsx")
INCIDENT_SHEET = "gtggungs2010toPresent"

OUTDIR = os.path.join(ROOT, "data", "regions", "us_tx", "results_corridor")

# Target state — change to run on other states in Phase B
TARGET_STATE = "TX"

# UTM CRS for Texas (matching your existing pipeline)
UTM_EPSG = 32614

# Buffer around each window (metres) for spatial join
# Matches the BUFFER_M used in 04_stats_and_bands.py
BUFFER_M = 2000

WINDOWS = [
    ("5km",  os.path.join(OUTDIR, "windows_5km.gpkg"),
             os.path.join(OUTDIR, "metrics_5km.csv"),
             os.path.join(OUTDIR, "metrics_5km_enriched.csv")),
    ("10km", os.path.join(OUTDIR, "windows_10km.gpkg"),
             os.path.join(OUTDIR, "metrics_10km.csv"),
             os.path.join(OUTDIR, "metrics_10km_enriched.csv")),
]

# ─────────────────────────────────────────────
# CAUSE WEIGHTS
# Higher weight = more dangerous cause type
# Rationale:
#   Corrosion       — structural failure, hard to detect, high consequence
#   Excavation      — third-party damage, preventable, high frequency
#   Material/Weld   — manufacturing defect, systemic risk
#   Natural Force   — external, unpredictable
#   Incorrect Op    — human error, preventable
#   Equipment       — mechanical, often lower consequence
#   Other           — baseline
# ─────────────────────────────────────────────

CAUSE_WEIGHTS = {
    "CORROSION FAILURE":                 1.0,
    "EXCAVATION DAMAGE":                 0.95,
    "MATERIAL FAILURE OF PIPE OR WELD":  0.85,
    "NATURAL FORCE DAMAGE":              0.75,
    "INCORRECT OPERATION":               0.70,
    "OTHER OUTSIDE FORCE DAMAGE":        0.65,
    "EQUIPMENT FAILURE":                 0.55,
    "OTHER INCIDENT CAUSE":              0.50,
}

REFERENCE_YEAR = 2024   # for pipe age calculation
MAX_PIPE_AGE   = 80     # years — cap for normalisation

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def _safe_float(val, default=0.0) -> float:
    try:
        v = float(val)
        return v if np.isfinite(v) else default
    except (TypeError, ValueError):
        return default


def _parse_year(val) -> float | None:
    """Return installation year as float, or None if unknown."""
    if val is None:
        return None
    s = str(val).strip().upper()
    if s in ("UNKNOWN", "UNK", "", "NAN", "NONE"):
        return None
    try:
        y = int(float(s))
        if 1900 <= y <= REFERENCE_YEAR:
            return float(y)
    except (ValueError, TypeError):
        pass
    return None


def _minmax(series: pd.Series) -> pd.Series:
    """Min-max normalise a series to [0, 1]. Returns 0 if constant."""
    mn, mx = series.min(), series.max()
    if mx == mn:
        return pd.Series(np.zeros(len(series)), index=series.index)
    return (series - mn) / (mx - mn)


# ─────────────────────────────────────────────
# STEP 1 — LOAD AND FILTER INCIDENTS
# ─────────────────────────────────────────────

def load_incidents(xlsx_path: str, sheet: str, state: str) -> pd.DataFrame:
    print(f"\n[1] Loading incidents for state: {state}")

    cols_needed = [
        "ONSHORE_STATE_ABBREVIATION",
        "LOCATION_LATITUDE",
        "LOCATION_LONGITUDE",
        "CAUSE",
        "PIPE_DIAMETER",
        "INSTALLATION_YEAR",
        "TOTAL_COST_CURRENT",
        "FATAL",
        "INJURE",
        "IYEAR",
    ]

    df = pd.read_excel(xlsx_path, sheet_name=sheet, usecols=cols_needed)
    df = df[df["ONSHORE_STATE_ABBREVIATION"].astype(str).str.strip() == state].copy()
    df = df.dropna(subset=["LOCATION_LATITUDE", "LOCATION_LONGITUDE"]).copy()
    df = df.reset_index(drop=True)

    print(f"    Incidents in {state}: {len(df)}")
    return df


# ─────────────────────────────────────────────
# STEP 2 — COMPUTE HAZARD SCORE PER INCIDENT
# ─────────────────────────────────────────────

def compute_hazard_scores(df: pd.DataFrame) -> pd.DataFrame:
    print("\n[2] Computing multivariate hazard scores")
    df = df.copy()

    # ── Sub-score A: Consequence severity ──────────────────────────────────
    # Combines fatalities (weight 3), injuries (weight 1), and log-cost
    # Rationale: fatality >> injury >> economic cost
    df["_fatal"]  = df["FATAL"].fillna(0).apply(_safe_float)
    df["_injure"] = df["INJURE"].fillna(0).apply(_safe_float)
    df["_cost"]   = df["TOTAL_COST_CURRENT"].fillna(0).apply(_safe_float)

    # Log-transform cost to reduce extreme outlier dominance
    df["_log_cost"] = np.log1p(df["_cost"])

    severity_raw = (
        df["_fatal"]  * 3.0 +
        df["_injure"] * 1.0 +
        _minmax(df["_log_cost"])
    )
    df["score_severity"] = _minmax(severity_raw)

    # ── Sub-score B: Cause type weight ─────────────────────────────────────
    cause_clean = df["CAUSE"].astype(str).str.strip().str.upper()
    df["score_cause"] = cause_clean.map(
        {k.upper(): v for k, v in CAUSE_WEIGHTS.items()}
    ).fillna(0.50)   # unknown causes get baseline weight

    # ── Sub-score C: Asset vulnerability ───────────────────────────────────
    # Older + larger diameter pipes = higher vulnerability
    # Age proxy: current year minus installation year (normalised)
    years = df["INSTALLATION_YEAR"].apply(_parse_year)
    age_raw = years.apply(
        lambda y: float(REFERENCE_YEAR - y) if not pd.isna(y) else float(MAX_PIPE_AGE * 0.6)
    )
    age_norm = (age_raw.clip(0, MAX_PIPE_AGE) / MAX_PIPE_AGE)

    # Diameter: larger pipes carry more volume = higher consequence
    median_diam = df["PIPE_DIAMETER"].median()
    if pd.isna(median_diam):
        median_diam = 12.75   # national median fallback
    diam_filled = df["PIPE_DIAMETER"].fillna(median_diam).apply(_safe_float)
    diam_norm   = _minmax(pd.Series(diam_filled))

    df["score_vulnerability"] = 0.6 * age_norm + 0.4 * diam_norm

    # ── Composite hazard score ──────────────────────────────────────────────
    # Weighted sum of three sub-scores:
    #   Cause type:     40% (most controllable, differentiates risk type)
    #   Consequence:    35% (direct impact measure)
    #   Vulnerability:  25% (asset condition proxy)
    df["hazard_score"] = (
        0.40 * df["score_cause"] +
        0.35 * df["score_severity"] +
        0.25 * df["score_vulnerability"]
    )

    print(f"    Hazard score — min: {df['hazard_score'].min():.4f}  "
          f"mean: {df['hazard_score'].mean():.4f}  "
          f"max: {df['hazard_score'].max():.4f}")
    print(f"    Score breakdown (means):")
    print(f"      severity:      {df['score_severity'].mean():.4f}")
    print(f"      cause:         {df['score_cause'].mean():.4f}")
    print(f"      vulnerability: {df['score_vulnerability'].mean():.4f}")

    return df


# ─────────────────────────────────────────────
# STEP 3 — BUILD GEODATAFRAME FROM INCIDENTS
# ─────────────────────────────────────────────

def incidents_to_gdf(df: pd.DataFrame, utm_epsg: int) -> gpd.GeoDataFrame:
    print("\n[3] Converting incidents to spatial GeoDataFrame")
    gdf = gpd.GeoDataFrame(
        df,
        geometry=gpd.points_from_xy(df["LOCATION_LONGITUDE"], df["LOCATION_LATITUDE"]),
        crs="EPSG:4326"
    )
    gdf = gdf.to_crs(epsg=utm_epsg)
    print(f"    GeoDataFrame: {len(gdf)} points in EPSG:{utm_epsg}")
    return gdf


# ─────────────────────────────────────────────
# STEP 4 — SPATIAL JOIN TO WINDOWS
# ─────────────────────────────────────────────

def enrich_windows(
    tag: str,
    win_gpkg: str,
    metrics_csv: str,
    out_csv: str,
    inc_gdf: gpd.GeoDataFrame,
    utm_epsg: int,
    buffer_m: float,
) -> pd.DataFrame:

    print(f"\n[4] Processing windows: {tag}")

    # Load windows
    if not os.path.exists(win_gpkg):
        print(f"    WARNING: {win_gpkg} not found — skipping {tag}")
        return None

    w = gpd.read_file(win_gpkg, layer="windows")
    w = w[w.geometry.notna()].copy()

    if w.crs is None:
        w = w.set_crs(epsg=utm_epsg)
    else:
        w = w.to_crs(epsg=utm_epsg)

    print(f"    Windows loaded: {len(w)}")

    # Read original metrics to preserve exposure_count
    orig = pd.read_csv(metrics_csv)
    exposure_lookup = orig.set_index("win_id")["exposure_count"].to_dict()

    # Buffer windows for spatial join
    w_buf = w.copy()
    w_buf["geometry"] = w_buf.geometry.buffer(buffer_m)

    # Spatial join: incidents within buffered windows
    inc_cols = ["geometry", "hazard_score", "score_severity",
                "score_cause", "score_vulnerability"]
    joined = gpd.sjoin(
        inc_gdf[inc_cols],
        w_buf[["win_id", "geometry"]],
        predicate="within",
        how="inner"
    )

    print(f"    Incident-window matches: {len(joined)}")

    # Aggregate per window
    agg = joined.groupby("win_id").agg(
        incident_count   = ("hazard_score", "count"),
        sum_hazard       = ("hazard_score", "sum"),
        mean_severity    = ("score_severity", "mean"),
        mean_cause_wt    = ("score_cause", "mean"),
        mean_vulnerability = ("score_vulnerability", "mean"),
    ).reset_index()

    # Build output aligned to all window IDs
    all_win_ids = w["win_id"].tolist()
    out = pd.DataFrame({"win_id": all_win_ids})
    out = out.merge(agg, on="win_id", how="left")

    out["incident_count"]    = out["incident_count"].fillna(0).astype(int)
    out["sum_hazard"]        = out["sum_hazard"].fillna(0.0)
    out["mean_severity"]     = out["mean_severity"].fillna(0.0)
    out["mean_cause_wt"]     = out["mean_cause_wt"].fillna(0.0)
    out["mean_vulnerability"]= out["mean_vulnerability"].fillna(0.0)

    # Restore exposure_count from original metrics
    out["exposure_count"] = out["win_id"].map(exposure_lookup).fillna(1).astype(int)

    # NEW risk_obs = sum of hazard scores / exposure_count
    # This replaces the raw incident_count / exposure_count density
    safe_exp = out["exposure_count"].clip(lower=1).astype(float)
    out["risk_obs"] = out["sum_hazard"] / safe_exp

    # Report
    n_with_risk = (out["risk_obs"] > 0).sum()
    print(f"    Windows with risk_obs > 0: {n_with_risk} / {len(out)}")
    print(f"    risk_obs — max: {out['risk_obs'].max():.4f}  "
          f"mean (nonzero): {out.loc[out['risk_obs']>0,'risk_obs'].mean():.4f}")

    # Save
    os.makedirs(os.path.dirname(out_csv), exist_ok=True)
    cols_out = [
        "win_id", "exposure_count", "incident_count",
        "risk_obs", "sum_hazard",
        "mean_severity", "mean_cause_wt", "mean_vulnerability"
    ]
    out[cols_out].to_csv(out_csv, index=False)
    print(f"    Saved: {out_csv}")

    return out


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    # Validate inputs
    for path, label in [(INCIDENT_XLSX, "Incident XLSX"), (OUTDIR, "Output dir")]:
        if not os.path.exists(path):
            print(f"ERROR: {label} not found: {path}")
            sys.exit(1)

    # Load and score incidents
    df  = load_incidents(INCIDENT_XLSX, INCIDENT_SHEET, TARGET_STATE)
    df  = compute_hazard_scores(df)
    gdf = incidents_to_gdf(df, UTM_EPSG)

    # Process each window resolution
    results = {}
    for tag, win_gpkg, metrics_csv, out_csv in WINDOWS:
        r = enrich_windows(
            tag=tag,
            win_gpkg=win_gpkg,
            metrics_csv=metrics_csv,
            out_csv=out_csv,
            inc_gdf=gdf,
            utm_epsg=UTM_EPSG,
            buffer_m=BUFFER_M,
        )
        if r is not None:
            results[tag] = r

    # Final summary
    print("\n" + "="*55)
    print("TASK A1 COMPLETE — Summary")
    print("="*55)
    for tag, r in results.items():
        total  = len(r)
        active = (r["risk_obs"] > 0).sum()
        maxr   = r["risk_obs"].max()
        print(f"\n  {tag}:")
        print(f"    Total windows:         {total:,}")
        print(f"    Windows with risk > 0: {active:,}  "
              f"({100*active/total:.1f}%)")
        print(f"    Max risk_obs:          {maxr:.4f}")

    print("\nNext step:")
    print("  Open 04_stats_and_bands.py and update CASES to use")
    print("  the enriched metrics files:")
    for tag, _, _, out_csv in WINDOWS:
        print(f"    ({tag!r}, ..., {os.path.basename(out_csv)!r})")
    print("\nThen re-run 04_stats_and_bands.py")


if __name__ == "__main__":
    main()
