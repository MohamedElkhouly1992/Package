# Chiller Degradation Evaluator — Large File Edition

This version is prepared for the ~409.5 MB ChillerPlant CSV files.

## Required GitHub structure

```text
your-repository/
├── streamlit_app.py
├── requirements.txt
└── .streamlit/
    └── config.toml
```

The hidden `.streamlit/config.toml` file is essential.

It contains:

```toml
[server]
maxUploadSize = 2000
maxMessageSize = 2000
```

After adding these files to GitHub, reboot/redeploy the Streamlit app.

## Memory-safe design

Upload one clean file and one degraded file at a time. The app reads only:

- `Datetime`
- `CWL_SEC_LOAD`
- `CHL_POW_1`
- `CHL_POW_2`
- `CHL_POW_3`

instead of loading all 78 columns.

Increasing the upload limit does not increase Streamlit Community Cloud RAM. For batch analysis of several 400+ MB files, Google Colab + Drive remains more robust.
