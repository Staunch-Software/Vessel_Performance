import pandas as pd
import os

def clean_excel_report(file_path):
    """Reads and cleans the legacy excel file."""
    # Read excel, handle cases where header might not be on row 0
    df = pd.read_excel(file_path)
    
    # 1. Remove completely empty rows/columns
    df = df.dropna(how="all").dropna(axis=1, how="all")
    
    # 2. Standardize column names (strip spaces)
    df.columns = [str(c).strip() for c in df.columns]
    
    # 3. Fill forward vessel name if it's only in the first row
    if 'Vessel Name' in df.columns:
        df['Vessel Name'] = df['Vessel Name'].ffill()
        
    return df