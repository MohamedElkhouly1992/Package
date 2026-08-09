# Chiller Degradation Evaluator

## What it does
Compares a clean chiller-plant CSV with one or more degraded/fouled CSVs on aligned timestamps.

Outputs:
- cooling energy (MWhth)
- chiller electricity (MWh)
- effective chiller COP
- observed COP reduction (%)
- observed COP health factor
- chiller electricity penalty (%)
- cooling change (%)
- daily COP-loss time series
- daily degradation flags using a user-selected screening threshold

The app recognizes filenames such as `_095.csv` as health factor F=0.95 and `_065.csv` as F=0.65.

## Run locally
```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

## Streamlit Cloud
Upload `streamlit_app.py` and `requirements.txt` to a GitHub repository, then deploy the repository in Streamlit Community Cloud.

## Data assumptions for the supplied ChillerPlant files
- timestamp: `Datetime`
- cooling load: `CWL_SEC_LOAD`
- load unit: W (converted to kW internally)
- chiller power columns: all columns beginning `CHL_POW_`

## Academic interpretation
Observed chiller COP:
COP = Q_cool / P_chiller

Observed COP degradation:
D_COP = 1 - COP_degraded/COP_clean

If F_chiller is a remaining-performance factor:
COP_f = COP_ff * F_chiller
and nominal degradation severity is:
delta_f = 1 - F_chiller

For a strict degradation-only causal comparison, preserve weather, required cooling load, and non-degradation control settings across clean and degraded cases.
