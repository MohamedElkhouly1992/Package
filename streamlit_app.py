import io
import re
import numpy as np
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Chiller Degradation Evaluator", layout="wide")
st.title("Chiller Degradation Evaluator")
st.caption("Paired clean-vs-degraded analysis for chiller fouling / heat-exchanger degradation.")

def read_csv(uploaded):
    return pd.read_csv(uploaded)

def infer_health_factor(name):
    # Recognizes names such as ..._095.csv -> 0.95 and ..._065.csv -> 0.65
    m = re.search(r'_(\d{3})(?:\D|$)', name)
    if not m:
        return np.nan
    x = int(m.group(1))
    return x / 100.0 if x >= 10 else x / 1000.0

def prepare(df, time_col, load_col, power_cols, load_scale):
    x = df[[time_col, load_col] + power_cols].copy()
    x[time_col] = pd.to_datetime(x[time_col], errors="coerce")
    x = x.dropna(subset=[time_col]).sort_values(time_col).drop_duplicates(time_col)
    for c in [load_col] + power_cols:
        x[c] = pd.to_numeric(x[c], errors="coerce")
    x["Q_kW"] = x[load_col] * load_scale
    x["P_chiller_kW"] = x[power_cols].sum(axis=1, min_count=1)
    return x.dropna(subset=["Q_kW", "P_chiller_kW"])

def integrated_kwh(series, dt_hours):
    return float(series.sum() * dt_hours)

def median_timestep_hours(t):
    d = t.sort_values().diff().dropna().dt.total_seconds()
    if d.empty:
        return 1/60
    return float(d.median() / 3600.0)

def overall_metrics(df, dt_hours):
    q_kwh = integrated_kwh(df["Q_kW"], dt_hours)
    e_kwh = integrated_kwh(df["P_chiller_kW"], dt_hours)
    cop = q_kwh / e_kwh if e_kwh > 0 else np.nan
    return q_kwh, e_kwh, cop

def daily_metrics(pair, time_col):
    z = pair.set_index(time_col)
    out = pd.DataFrame()
    for label in ["clean", "deg"]:
        q = z[f"Q_kW_{label}"].resample("D").sum()
        p = z[f"P_chiller_kW_{label}"].resample("D").sum()
        out[f"COP_{label}"] = q / p.replace(0, np.nan)
    out["COP_reduction_pct"] = 100.0 * (1.0 - out["COP_deg"] / out["COP_clean"])
    return out.reset_index()

clean_file = st.file_uploader("1) Upload CLEAN baseline CSV", type=["csv"])
deg_files = st.file_uploader(
    "2) Upload one or more DEGRADED CSV files",
    type=["csv"],
    accept_multiple_files=True
)

with st.sidebar:
    st.header("Data definition")
    time_col = st.text_input("Timestamp column", "Datetime")
    load_col = st.text_input("Cooling-load column", "CWL_SEC_LOAD")
    power_prefix = st.text_input("Chiller-power prefix", "CHL_POW_")
    load_unit = st.selectbox("Cooling-load unit in CSV", ["W", "kW"], index=0)
    threshold = st.number_input(
        "Daily COP-loss screening threshold (%)",
        min_value=0.0, max_value=100.0, value=3.0, step=0.5
    )
    st.caption("The threshold is a screening choice, not a universal fouling standard.")

if clean_file and deg_files:
    clean_raw = read_csv(clean_file)

    missing = [c for c in [time_col, load_col] if c not in clean_raw.columns]
    if missing:
        st.error(f"Missing baseline column(s): {missing}")
        st.stop()

    power_cols = [c for c in clean_raw.columns if c.startswith(power_prefix)]
    if not power_cols:
        st.error(f"No baseline power columns found with prefix '{power_prefix}'.")
        st.stop()

    load_scale = 0.001 if load_unit == "W" else 1.0
    clean = prepare(clean_raw, time_col, load_col, power_cols, load_scale)
    dt_hours = median_timestep_hours(clean[time_col])

    q0, e0, cop0 = overall_metrics(clean, dt_hours)

    st.subheader("Baseline")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Records", f"{len(clean):,}")
    c2.metric("Cooling", f"{q0/1000:,.2f} MWhth")
    c3.metric("Chiller electricity", f"{e0/1000:,.2f} MWh")
    c4.metric("Effective chiller COP", f"{cop0:.4f}")

    rows = []
    daily_all = []

    for uploaded in deg_files:
        deg_raw = read_csv(uploaded)
        missing = [c for c in [time_col, load_col] + power_cols if c not in deg_raw.columns]
        if missing:
            st.warning(f"{uploaded.name}: skipped; missing {missing}")
            continue

        deg = prepare(deg_raw, time_col, load_col, power_cols, load_scale)

        pair = clean[[time_col, "Q_kW", "P_chiller_kW"]].merge(
            deg[[time_col, "Q_kW", "P_chiller_kW"]],
            on=time_col, how="inner", suffixes=("_clean", "_deg")
        )
        if pair.empty:
            st.warning(f"{uploaded.name}: no aligned timestamps with baseline.")
            continue

        qd = integrated_kwh(pair["Q_kW_deg"], dt_hours)
        ed = integrated_kwh(pair["P_chiller_kW_deg"], dt_hours)
        copd = qd / ed if ed > 0 else np.nan

        q0_pair = integrated_kwh(pair["Q_kW_clean"], dt_hours)
        e0_pair = integrated_kwh(pair["P_chiller_kW_clean"], dt_hours)
        cop0_pair = q0_pair / e0_pair if e0_pair > 0 else np.nan

        observed_cop_loss = 100.0 * (1.0 - copd / cop0_pair)
        energy_penalty = 100.0 * (ed / e0_pair - 1.0)
        cooling_change = 100.0 * (qd / q0_pair - 1.0)
        observed_health = copd / cop0_pair

        hf = infer_health_factor(uploaded.name)
        nominal_deg = 100.0 * (1.0 - hf) if np.isfinite(hf) else np.nan
        expected_cop = cop0_pair * hf if np.isfinite(hf) else np.nan

        d = daily_metrics(pair, time_col)
        d["scenario"] = uploaded.name
        d["degradation_flag"] = d["COP_reduction_pct"] >= threshold
        daily_all.append(d)

        rows.append({
            "scenario": uploaded.name,
            "aligned_records": len(pair),
            "cooling_MWhth": qd/1000,
            "chiller_energy_MWh": ed/1000,
            "effective_COP": copd,
            "observed_COP_reduction_pct": observed_cop_loss,
            "observed_COP_health_factor": observed_health,
            "chiller_energy_penalty_pct": energy_penalty,
            "cooling_change_pct": cooling_change,
            "nominal_health_factor_from_filename": hf,
            "nominal_degradation_pct_1_minus_F": nominal_deg,
            "reference_model_expected_COP": expected_cop,
        })

    if not rows:
        st.stop()

    summary = pd.DataFrame(rows)

    st.subheader("Degradation summary")
    st.dataframe(summary, use_container_width=True)

    st.download_button(
        "Download summary CSV",
        summary.to_csv(index=False).encode("utf-8"),
        "degradation_summary.csv",
        "text/csv",
    )

    if daily_all:
        daily = pd.concat(daily_all, ignore_index=True)
        st.subheader("Daily COP-loss trend")
        pivot = daily.pivot(index=time_col, columns="scenario", values="COP_reduction_pct")
        st.line_chart(pivot)

        flags = (
            daily.groupby("scenario")["degradation_flag"]
            .agg(["sum", "count"])
            .rename(columns={"sum": "flagged_days", "count": "valid_days"})
        )
        flags["flagged_fraction_pct"] = 100.0 * flags["flagged_days"] / flags["valid_days"]
        st.dataframe(flags, use_container_width=True)

        st.download_button(
            "Download daily degradation series",
            daily.to_csv(index=False).encode("utf-8"),
            "daily_degradation_timeseries.csv",
            "text/csv",
        )

    st.subheader("Equations used")
    st.latex(r"COP=\frac{Q_{cool}}{P_{chiller}}")
    st.latex(r"D_{COP}=1-\frac{COP_{degraded}}{COP_{clean}}")
    st.latex(r"H_{COP}=\frac{COP_{degraded}}{COP_{clean}}=1-D_{COP}")
    st.latex(r"COP_f=COP_{ff}F_{chiller}")
    st.latex(r"\delta_f=1-F_{chiller}")

    st.info(
        "Interpretation: this app calculates CHILLER-only COP. It intentionally excludes "
        "secondary pumps, primary pumps, condenser pumps and cooling-tower power. For a "
        "strict causal 'degradation-only' experiment, weather, imposed cooling demand and "
        "non-degradation control setpoints should be held identical between files."
    )
else:
    st.info("Upload the clean baseline and at least one degraded CSV to begin.")
