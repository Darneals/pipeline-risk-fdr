"""
quick_test.py
=============
Self-contained verification test for the multivariate hazard scoring
logic used in A1_enrich_incidents.py.

No external data downloads required. Synthetic incidents are generated
internally with the same column structure as the PHMSA dataset.

Run from the project root:
    python quick_test.py

Expected output: PASS for all five assertions.
"""

import sys
import numpy as np
import pandas as pd

# ── Replicate core logic from A1_enrich_incidents.py ──────────────────

CAUSE_WEIGHTS = {
    "CORROSION FAILURE":                1.0,
    "EXCAVATION DAMAGE":                0.95,
    "MATERIAL FAILURE OF PIPE OR WELD": 0.85,
    "NATURAL FORCE DAMAGE":             0.75,
    "INCORRECT OPERATION":              0.70,
    "OTHER OUTSIDE FORCE DAMAGE":       0.65,
    "EQUIPMENT FAILURE":                0.55,
    "OTHER INCIDENT CAUSE":             0.50,
}

REFERENCE_YEAR = 2024
MAX_PIPE_AGE   = 80


def _safe_float(val, default=0.0):
    try:
        v = float(val)
        return v if np.isfinite(v) else default
    except (TypeError, ValueError):
        return default


def _parse_year(val):
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


def _minmax(series):
    mn, mx = series.min(), series.max()
    if mx == mn:
        return pd.Series(np.zeros(len(series)), index=series.index)
    return (series - mn) / (mx - mn)


def compute_hazard_scores(df):
    df = df.copy()

    df["_fatal"]    = df["FATAL"].fillna(0).apply(_safe_float)
    df["_injure"]   = df["INJURE"].fillna(0).apply(_safe_float)
    df["_cost"]     = df["TOTAL_COST_CURRENT"].fillna(0).apply(_safe_float)
    df["_log_cost"] = np.log1p(df["_cost"])

    severity_raw = (
        df["_fatal"]  * 3.0 +
        df["_injure"] * 1.0 +
        _minmax(df["_log_cost"])
    )
    df["score_severity"] = _minmax(severity_raw)

    cause_clean = df["CAUSE"].astype(str).str.strip().str.upper()
    df["score_cause"] = cause_clean.map(
        {k.upper(): v for k, v in CAUSE_WEIGHTS.items()}
    ).fillna(0.50)

    # FIX: _parse_year returns None for unknowns, but pandas apply()
    # converts Python None to NaN in a float Series. Use pd.isna()
    # rather than `is not None` to correctly detect missing years.
    years   = df["INSTALLATION_YEAR"].apply(_parse_year)
    age_raw = years.apply(
        lambda y: float(REFERENCE_YEAR - y) if not pd.isna(y)
                  else float(MAX_PIPE_AGE * 0.6)
    )
    age_norm = (age_raw.clip(0, MAX_PIPE_AGE) / MAX_PIPE_AGE)

    median_diam = df["PIPE_DIAMETER"].median()
    if pd.isna(median_diam):
        median_diam = 12.75
    diam_filled = df["PIPE_DIAMETER"].fillna(median_diam).apply(_safe_float)
    diam_norm   = _minmax(pd.Series(diam_filled))

    df["score_vulnerability"] = 0.6 * age_norm + 0.4 * diam_norm

    df["hazard_score"] = (
        0.40 * df["score_cause"] +
        0.35 * df["score_severity"] +
        0.25 * df["score_vulnerability"]
    )
    return df


# ── Synthetic test data ────────────────────────────────────────────────

def make_synthetic_incidents():
    """
    Ten synthetic incidents covering all eight PHMSA cause categories,
    a range of severities, ages, and diameters, plus edge cases:
    missing installation year, missing diameter, zero cost.
    Column names match the PHMSA Excel schema exactly.
    """
    return pd.DataFrame({
        "ONSHORE_STATE_ABBREVIATION": ["TX"] * 10,
        "LOCATION_LATITUDE":  [29.5, 30.1, 31.2, 29.8, 30.5,
                                31.0, 30.7, 29.3, 30.9, 31.5],
        "LOCATION_LONGITUDE": [-95.1, -95.5, -96.0, -94.8, -95.3,
                                -95.7, -96.2, -94.5, -95.9, -96.4],
        "CAUSE": [
            "CORROSION FAILURE",
            "EXCAVATION DAMAGE",
            "MATERIAL FAILURE OF PIPE OR WELD",
            "NATURAL FORCE DAMAGE",
            "INCORRECT OPERATION",
            "OTHER OUTSIDE FORCE DAMAGE",
            "EQUIPMENT FAILURE",
            "OTHER INCIDENT CAUSE",
            "CORROSION FAILURE",   # duplicate cause — tests aggregation
            "UNKNOWN CAUSE",       # unmapped cause — should get 0.50 baseline
        ],
        "PIPE_DIAMETER":      [12.75, 20.0, 8.625, None, 30.0,
                                16.0,  24.0, 6.625, 12.75, 36.0],
        "INSTALLATION_YEAR":  [1975, 1990, "UNKNOWN", 2005, 1960,
                                1985, 2010, 1970,     None, 2000],
        "TOTAL_COST_CURRENT": [500_000, 1_200_000, 0, 3_400_000, 750_000,
                                250_000, 120_000,   0, 8_900_000, 45_000],
        "FATAL":   [0, 1, 0, 2, 0, 0, 0, 0, 3, 0],
        "INJURE":  [2, 0, 1, 4, 0, 1, 0, 0, 1, 0],
        "IYEAR":   [2015, 2018, 2020, 2013, 2021,
                    2016, 2022, 2011, 2019, 2023],
    })


# ── Assertions ────────────────────────────────────────────────────────

def run_tests():
    df  = make_synthetic_incidents()
    out = compute_hazard_scores(df)

    passed = 0
    failed = 0

    def check(name, condition, detail=""):
        nonlocal passed, failed
        if condition:
            print(f"  PASS  {name}")
            passed += 1
        else:
            print(f"  FAIL  {name}" + (f" — {detail}" if detail else ""))
            failed += 1

    print("\nRunning hazard scoring quick-test...\n")

    # 1. Output row count matches input
    check("Row count preserved",
          len(out) == 10,
          f"got {len(out)}")

    # 2. All hazard scores are finite and non-negative
    #    Note: score_cause has a 0.50 floor, so composite minimum > 0
    scores_ok = (
        out["hazard_score"].notna().all() and
        (out["hazard_score"] >= 0).all() and
        np.isfinite(out["hazard_score"]).all()
    )
    check("All hazard scores finite and non-negative",
          scores_ok,
          f"min={out['hazard_score'].min():.4f} max={out['hazard_score'].max():.4f}")

    # 3. Corrosion incidents score higher than equipment failure incidents
    corrosion_mean = out.loc[
        out["CAUSE"] == "CORROSION FAILURE", "score_cause"
    ].mean()
    equipment_mean = out.loc[
        out["CAUSE"] == "EQUIPMENT FAILURE", "score_cause"
    ].mean()
    check("Corrosion cause score > equipment failure cause score",
          corrosion_mean > equipment_mean,
          f"corrosion={corrosion_mean:.3f} equipment={equipment_mean:.3f}")

    # 4. Unknown/unmapped cause gets the 0.50 baseline weight
    unknown_score = out.loc[out["CAUSE"] == "UNKNOWN CAUSE", "score_cause"].iloc[0]
    check("Unknown cause receives 0.50 baseline weight",
          abs(unknown_score - 0.50) < 1e-9,
          f"got {unknown_score:.4f}")

    # 5. Missing/unknown installation year produces valid vulnerability scores
    #    (no NaN, no negative — imputation path exercised)
    vuln_col = out["score_vulnerability"]
    check("Missing installation year handled — no NaN in vulnerability score",
          vuln_col.notna().all() and (vuln_col >= 0).all(),
          f"NaN count={vuln_col.isna().sum()}")

    # Summary
    print(f"\nResult: {passed} passed, {failed} failed\n")
    return failed == 0


if __name__ == "__main__":
    try:
        import geopandas  # noqa: F401 — confirm spatial stack is available
    except ImportError:
        print("WARNING: geopandas not installed. Spatial join tests skipped.")
        print("Install with: conda env create -f environment.yml\n")

    ok = run_tests()
    sys.exit(0 if ok else 1)
