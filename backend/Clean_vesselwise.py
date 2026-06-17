import os
import pandas as pd
import numpy as np
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

# --- LOCAL (original hardcoded paths — uncomment to use) ---
# INPUT  = r'C:\Users\visha\Downloads\ozellar\Data_ingestion_pipeline\backend\Mariapps_logs_VesselWise.xlsx'
# OUTPUT = r'C:\Users\visha\Downloads\ozellar\Data_ingestion_pipeline\backend\Mariapps_logs_cleaned.xlsx'
# --- VM / CROSS-PLATFORM (env var, defaults relative to this file) ---
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT  = os.getenv("CLEAN_INPUT_FILE",  os.path.join(_BASE_DIR, 'Mariapps_logs_VesselWise.xlsx'))
OUTPUT = os.getenv("CLEAN_OUTPUT_FILE", os.path.join(_BASE_DIR, 'Mariapps_logs_cleaned.xlsx'))

SHEETS = [
    'mariapps_logs_expanded',
    'AM KIRTI - 9832925',
    'AM TARANG - 9832913',
    'AM UMANG - 9792058',
    'GCL GANGA - 9481697',
    'GCL NARMADA - 9481685',
    'GCL SABARMATI - 9481661',
    'GCL TAPI - 9481659',
    'GCL YAMUNA - 9481219',
]

cleaned_sheets = {}
hide_indices   = {}

for sheet in SHEETS:
    df = pd.read_excel(INPUT, sheet_name=sheet)
    df.drop(columns=['created_at'], errors='ignore', inplace=True)
    for col in df.columns:
        if df[col].dtype == object or str(df[col].dtype) == 'string':
            df[col] = df[col].replace(r'^\s*$', np.nan, regex=True)
    hide_indices[sheet] = [
        i + 1 for i, col in enumerate(df.columns)
        if df[col].isnull().all()
    ]
    for col in df.columns:
        df[col] = df[col].fillna(0)
    cleaned_sheets[sheet] = df
    print(f"[{sheet}] cols={len(df.columns)} to_hide={len(hide_indices[sheet])}")

with pd.ExcelWriter(OUTPUT, engine='openpyxl') as writer:
    for sheet, df in cleaned_sheets.items():
        df.to_excel(writer, sheet_name=sheet, index=False)

import xlwings as xw

app = xw.App(visible=False)
wb  = app.books.open(OUTPUT)

for sheet in SHEETS:
    ws = wb.sheets[sheet]
    for col_idx in hide_indices[sheet]:
        ws.api.Columns(col_idx).Hidden = True

wb.save()
wb.close()
app.quit()

print(f"\nDone! Saved -> {OUTPUT}")