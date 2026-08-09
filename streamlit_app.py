import re
import gc
import numpy as np
import pandas as pd
import streamlit as st

st.set_page_config(page_title='Chiller Degradation Evaluator', layout='wide')
st.title('Chiller Degradation Evaluator — Large File Edition')
st.caption('Paired clean-vs-degraded analysis. Upload limit configured to 2000 MB per file.')


def infer_health_factor(name):
    m = re.search(r'_(\d{3})(?:\D|$)', name)
    return int(m.group(1))/100.0 if m else np.nan


def read_reduced(uploaded, time_col, load_col, power_prefix, load_scale):
    uploaded.seek(0)
    header = pd.read_csv(uploaded, nrows=0)
    header_cols = list(header.columns)
    power_cols = [c for c in header_cols if c.startswith(power_prefix)]
    missing = [c for c in [time_col, load_col] if c not in header_cols]
    if missing:
        raise ValueError(f'Missing required column(s): {missing}')
    if not power_cols:
        raise ValueError(f"No chiller power columns found with prefix '{power_prefix}'.")
    usecols = [time_col, load_col] + power_cols

    uploaded.seek(0)
    df = pd.read_csv(uploaded, usecols=usecols, low_memory=False)
    df[time_col] = pd.to_datetime(df[time_col], errors='coerce')
    df = df.dropna(subset=[time_col]).sort_values(time_col).drop_duplicates(time_col)
    for c in [load_col] + power_cols:
        df[c] = pd.to_numeric(df[c], errors='coerce')
    df['Q_kW'] = df[load_col] * load_scale
    df['P_chiller_kW'] = df[power_cols].sum(axis=1, min_count=1)
    out = df[[time_col, 'Q_kW', 'P_chiller_kW']].dropna().copy()
    del df
    gc.collect()
    return out


def timestep_hours(t):
    d = t.sort_values().diff().dropna().dt.total_seconds()
    return float(d.median()/3600.0) if not d.empty else 1/60


def metrics(pair, time_col):
    dt = timestep_hours(pair[time_col])
    q0 = pair['Q_kW_clean'].sum()*dt
    e0 = pair['P_chiller_kW_clean'].sum()*dt
    qd = pair['Q_kW_deg'].sum()*dt
    ed = pair['P_chiller_kW_deg'].sum()*dt
    cop0 = q0/e0 if e0 > 0 else np.nan
    copd = qd/ed if ed > 0 else np.nan
    return {
        'cooling_MWhth': qd/1000,
        'chiller_energy_MWh': ed/1000,
        'effective_COP': copd,
        'observed_COP_reduction_pct': 100*(1-copd/cop0),
        'observed_COP_health_factor': copd/cop0,
        'chiller_energy_penalty_pct': 100*(ed/e0-1),
        'cooling_change_pct': 100*(qd/q0-1),
        'clean_COP_on_aligned_period': cop0,
    }


def daily_metrics(pair, time_col):
    z = pair.set_index(time_col)
    q0 = z['Q_kW_clean'].resample('D').sum()
    e0 = z['P_chiller_kW_clean'].resample('D').sum()
    qd = z['Q_kW_deg'].resample('D').sum()
    ed = z['P_chiller_kW_deg'].resample('D').sum()
    out = pd.DataFrame({
        'COP_clean': q0/e0.replace(0, np.nan),
        'COP_degraded': qd/ed.replace(0, np.nan),
    })
    out['COP_reduction_pct'] = 100*(1-out['COP_degraded']/out['COP_clean'])
    return out.reset_index()


with st.sidebar:
    st.header('Data definition')
    time_col = st.text_input('Timestamp column', 'Datetime')
    load_col = st.text_input('Cooling-load column', 'CWL_SEC_LOAD')
    power_prefix = st.text_input('Chiller-power prefix', 'CHL_POW_')
    load_unit = st.selectbox('Cooling-load unit in CSV', ['W','kW'], index=0)
    threshold = st.number_input('Daily COP-loss screening threshold (%)', 0.0, 100.0, 3.0, 0.5)

st.info('Large-file mode: upload the CLEAN file and ONE degraded file at a time to reduce Community Cloud memory use.')

clean_file = st.file_uploader('1) Upload CLEAN baseline CSV', type=['csv'], key='clean')
deg_file = st.file_uploader('2) Upload ONE DEGRADED CSV', type=['csv'], key='deg')

if clean_file and deg_file:
    scale = 0.001 if load_unit == 'W' else 1.0
    try:
        with st.status('Processing large CSV files...', expanded=True) as s:
            st.write('Reading baseline — only required columns...')
            clean = read_reduced(clean_file, time_col, load_col, power_prefix, scale)
            st.write('Reading degraded case — only required columns...')
            deg = read_reduced(deg_file, time_col, load_col, power_prefix, scale)
            st.write('Aligning timestamps...')
            pair = clean.merge(deg, on=time_col, how='inner', suffixes=('_clean','_deg'))
            s.update(label='Analysis complete', state='complete', expanded=False)
    except Exception as exc:
        st.error(str(exc))
        st.stop()

    if pair.empty:
        st.error('No common valid timestamps between the two files.')
        st.stop()

    r = metrics(pair, time_col)
    F = infer_health_factor(deg_file.name)
    nominal = 100*(1-F) if np.isfinite(F) else np.nan

    c1,c2,c3,c4 = st.columns(4)
    c1.metric('Aligned records', f"{len(pair):,}")
    c2.metric('Effective chiller COP', f"{r['effective_COP']:.4f}")
    c3.metric('Observed COP loss', f"{r['observed_COP_reduction_pct']:.2f}%")
    c4.metric('Chiller energy penalty', f"{r['chiller_energy_penalty_pct']:.2f}%")

    summary = pd.DataFrame([{
        'scenario': deg_file.name,
        **r,
        'nominal_health_factor_F': F,
        'nominal_degradation_pct_1_minus_F': nominal,
    }])
    st.subheader('Annual degradation summary')
    st.dataframe(summary, use_container_width=True)
    st.download_button('Download annual summary CSV', summary.to_csv(index=False).encode('utf-8'), 'annual_degradation_summary.csv', 'text/csv')

    daily = daily_metrics(pair, time_col)
    daily['degradation_flag'] = daily['COP_reduction_pct'] >= threshold
    st.subheader('Daily COP degradation')
    st.line_chart(daily.set_index(time_col)[['COP_reduction_pct']])
    valid = int(daily['COP_reduction_pct'].notna().sum())
    flagged = int(daily['degradation_flag'].sum())
    st.write(f'Days at or above {threshold:.1f}% COP loss: **{flagged} / {valid}**')
    st.download_button('Download daily degradation CSV', daily.to_csv(index=False).encode('utf-8'), 'daily_COP_degradation.csv', 'text/csv')

    st.subheader('Equations')
    st.latex(r'COP=\frac{\sum Q_{cool}\Delta t}{\sum P_{chiller}\Delta t}')
    st.latex(r'D_{COP}=1-\frac{COP_{degraded}}{COP_{clean}}')
    st.latex(r'H_{COP}=\frac{COP_{degraded}}{COP_{clean}}')
    st.latex(r'\delta_f=1-F_{chiller}')

    st.warning('For a strict degradation-only experiment, keep weather, required load, and non-degradation setpoints fixed between the two cases.')

    del clean, deg, pair
    gc.collect()
else:
    st.info('Upload the clean baseline and one degraded CSV to begin.')
