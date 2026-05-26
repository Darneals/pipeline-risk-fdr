# Geospatial Decision Support Framework for FDR-Validated Pipeline Risk Detection
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

> **Paper:** *A Geospatial Decision Support Framework for FDR-Validated Pipeline Risk Hotspot Detection Across Multi-State Transmission Networks Using Immersive WebGL Visualisation*
> **Authors:** Daniel Tonye Oyefidein, Hitham Alhussian, Said Jadid Abdulkadir, Shamsuddeen Adamu, Afroza Afrin
> **Institution:** Universiti Teknologi PETRONAS, Malaysia
> **Repository:** https://github.com/Darneals/pipeline-risk-fdr

---

## Overview

This repository contains all analysis scripts and the WebGL frontend for a reproducible geospatial decision support framework for corridor-scale natural gas pipeline risk detection using publicly available federal data.

The framework:
- Constructs a **multivariate hazard score** from PHMSA incident attributes (cause type, consequence severity, asset vulnerability)
- Applies a **corridor-level Benjamini–Hochberg FDR correction** that resolves the BH multiplicity gap in national-scale pipeline corridor testing
- Validates results across **three U.S. states** (Texas, Louisiana, Oklahoma) at two spatial resolutions (5 km and 10 km)
- Renders FDR-validated risk corridors in a **WebGL 3D immersive environment** where extrusion height maps exclusively to corridor z-score

**Key results:** 267 FDR-significant risk corridors identified at 5 km resolution across TX, LA, and OK. Peak z-score 55.74 (Louisiana). Mean SUS 76.67 across nine domain specialist evaluators.

---

## Repository Structure

```
cd pipeline-risk-fdr
│
├── scripts/
│   └── corridor/
│       ├── A1_enrich_incidents.py      # Multivariate hazard score computation
│       ├── A2_corridor_fdr.py          # Corridor-level permutation test + BH-FDR
│       ├── B_multistate_expansion.py   # Multi-state pipeline (TX, LA, OK)
│       ├── 02_make_windows.py          # Sliding corridor window generation
│       ├── 04_stats_and_bands.py       # Window-level statistics
│       ├── 05_make_ribbons.py          # Polygon ribbon generation for WebGL
│       ├── D1_figures.py               # Publication figures (Fig. 1–8)
│       ├── D2_crossstate_map.py        # Cross-state risk maps (Fig. 9)
│       └── D3_architecture.py          # System architecture diagram (Fig. 10)
│
├── phase9/
│   ├── backend/
│   │   └── app.py                      # FastAPI backend server
│   └── frontend/
│       ├── src/
│       │   ├── App.jsx                  # Root React component
│       │   ├── views/MapView.jsx        # MapLibre GL 3D rendering
│       │   └── api.js                   # Backend API client
│       ├── package.json
│       └── vite.config.js
│
├── data/                               # NOT INCLUDED — see Data Setup below
├── figures/                            # NOT INCLUDED — regenerate with D1-D3
├── environment.yml                     # Conda environment specification
└── README.md
```

---

## Data Setup

The raw data is **not included** in this repository because it is publicly available from federal sources. Download and place as follows:

### 1. PHMSA Incident Records
- URL: https://www.phmsa.dot.gov/data-and-statistics/pipeline/gas-distribution-gas-gathering-gas-transmission-hazardous-liquids
- Download: **Gas Transmission and Gathering Significant Incident Files**
- Save as: `data/raw/gtggungs2010toPresent.xlsx`

### 2. National Pipeline Shapefile
- URL: https://www.phmsa.dot.gov/resources/npms
- Download: **National Pipeline Mapping System — Gas Transmission Shapefile**
- Save as: `data/raw/Natural_Gas_Interstate_and_Intrastate_Pipelines/`

### 3. State Boundaries (TIGER/Line)
- URL: https://www.census.gov/geographies/mapping-files/time-series/geo/tiger-line-file.html
- Download: **States and Equivalent Entities (2018)**
- Save as: `data/raw/cb_2018_us_state_500k/`

### Expected directory structure after data setup
```
data/
└── raw/
    ├── gtggungs2010toPresent.xlsx
    ├── Natural_Gas_Interstate_and_Intrastate_Pipelines/
    │   └── *.shp (and associated files)
    └── cb_2018_us_state_500k/
        └── *.shp (and associated files)
```

---

## Installation

### Prerequisites
- [Anaconda](https://www.anaconda.com/download) or [Miniconda](https://docs.conda.io/en/latest/miniconda.html)
- [Node.js](https://nodejs.org/) v18 or higher (for the frontend)
- Git

### Step 1 — Clone the repository
```bash
git clone https://github.com/Darneals/pipeline-risk-fdr.git
cd pipeline-risk-fdr
```

### Step 2 — Create the Python environment
```bash
conda env create -f environment.yml
conda activate rim12
```

### Step 3 — Install frontend dependencies
```bash
cd phase9/frontend
npm install
cd ../..
```

---

## Running the Analysis

All scripts must be run from the **project root** with the `rim12` environment active.

```bash
conda activate rim12
cd C:\path\to\icvars-pipeline-risk
```

### Step 1 — Enrich incidents with hazard scores
```bash
python scripts/corridor/A1_enrich_incidents.py
```
*Output:* Enriched incident CSV files per state in `data/regions/{state}/`

### Step 2 — Generate corridor windows
```bash
python scripts/corridor/02_make_windows.py
```
*Output:* Window GeoJSON files at 5 km and 10 km resolution per state

### Step 3 — Compute window-level statistics
```bash
python scripts/corridor/04_stats_and_bands.py
```
*Output:* `metrics_{res}_enriched.csv` per state per resolution

### Step 4 — Run corridor-level FDR correction
```bash
python scripts/corridor/A2_corridor_fdr.py
```
*Output:* `corridor_fdr_{res}.csv` and `risk_windows_{res}_corridorfdr.geojson` per state

### Step 5 — Multi-state expansion (TX, LA, OK)
```bash
python scripts/corridor/B_multistate_expansion.py
```
*Output:* All corridor FDR results for all three states at both resolutions

### Step 6 — Generate ribbon polygons for WebGL
```bash
python scripts/corridor/05_make_ribbons.py
```
*Output:* `risk_windows_{res}_ribbon.geojson` per state per resolution

### Step 7 — Generate publication figures
```bash
python scripts/corridor/D1_figures.py
python scripts/corridor/D2_crossstate_map.py
python scripts/corridor/D3_architecture.py
```
*Output:* All figures in `figures/` at 600 DPI (PNG and SVG)

---

## Running the WebGL Visualisation

The visualisation requires both the backend server and the frontend development server to be running simultaneously.

### Terminal 1 — Start the backend
```bash
conda activate rim12
cd phase9/backend
uvicorn app:app --reload --port 8000
```

### Terminal 2 — Start the frontend
```bash
cd phase9/frontend
npm run dev
```

Open your browser at **http://localhost:5173**

### Using the interface
- Use the **Region** dropdown to switch between Texas (TX), Louisiana (LA), and Oklahoma (OK)
- Toggle **5 km / 10 km** resolution
- Enable **3D mode** to see corridors extruded by z-score magnitude
- Enable **Story mode** for the five-tier risk band colour classification
- Hover over any corridor to view the **corridor telemetry** (z-score, q-value, significance flag)

---

## Remote Evaluation Deployment (ngrok)

To share the system with remote evaluators:

```bash
# With both backend and frontend running:
ngrok http 5173
```

Set `VITE_API_BASE` in `phase9/frontend/.env` to the ngrok HTTPS URL before starting the frontend.

---

## Reproducing Paper Results

The verified results from the paper are:

| State | Resolution | Corridors tested | FDR-significant | Z_max  | q_min  |
|-------|------------|-----------------|-----------------|--------|--------|
| TX    | 5 km       | 4,649           | 107             | 43.70  | 0.0434 |
| TX    | 10 km      | 2,091           | 56              | 48.42  | 0.0373 |
| LA    | 5 km       | 1,401           | 93              | 55.74  | 0.0187 |
| LA    | 10 km      | 847             | 77              | 25.36  | 0.0134 |
| OK    | 5 km       | 1,623           | 67              | 28.73  | 0.0266 |
| OK    | 10 km      | 938             | 51              | 27.68  | 0.0191 |

Permutation count: B = 999. FDR threshold: α = 0.05. All results are reproducible by following the pipeline above.

---

## Quick Test

To verify the core hazard scoring logic without downloading the full PHMSA datasets, run the self-contained test script from the project root:

```bash
python quick_test.py
```

No external data files are required. The script generates ten synthetic incidents internally using the same column schema as the PHMSA Excel file and runs them through the full hazard scoring pipeline (`A1_enrich_incidents.py` logic).

Expected output:

```
Running hazard scoring quick-test...

  PASS  Row count preserved
  PASS  All hazard scores finite and non-negative
  PASS  Corrosion cause score > equipment failure cause score
  PASS  Unknown cause receives 0.50 baseline weight
  PASS  Missing installation year handled — no NaN in vulnerability score

Result: 5 passed, 0 failed
```

The test covers:
- All eight PHMSA cause categories including the unmapped baseline
- Missing and string-encoded installation years (`"UNKNOWN"`, `None`)
- Missing pipe diameter (median imputation)
- Zero-cost and multi-fatality edge cases

> **Note:** A `WARNING: geopandas not installed` message may appear if the conda environment has not been activated. This only affects the spatial join stage; all five scoring tests run on NumPy and pandas alone. To activate the full environment: `conda activate rim12`


```

---

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.

The PHMSA datasets used in this study are in the public domain and available from the U.S. Department of Transportation.

---

## Contact

Daniel Tonye Oyefidein
Department of Computing, Universiti Teknologi PETRONAS
daniel_24001664@utp.edu.my
