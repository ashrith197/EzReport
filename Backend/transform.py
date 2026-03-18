import os
import re
import json
import sqlite3
import pandas as pd
from pathlib import Path
from dotenv import load_dotenv

def process_and_store_data(df, db_path='data.db', table_name='data'):
    """
    Cleans column names, infers data types, stores in SQLite, and returns schema.
    """
    # 1. Clean column names to lowercase with underscores
    df.columns = [re.sub(r'[^a-zA-Z0-9]+', '_', col).strip('_').lower() for col in df.columns]

    # 2. Treat null values
    # Decision: Leaving null values as pandas NA/NaN allows SQLite to natively store them as NULL.
    # This preserves the missing state without artificially skewing analytics.

    schema = {
        "table_name": table_name,
        "columns": []
    }

    # 3. Parse dates and infer data types
    for col in df.columns:
        # Check if column is object/string to attempt date parsing
        if pd.api.types.is_object_dtype(df[col]) or pd.api.types.is_string_dtype(df[col]):
            sample = df[col].dropna()
            if not sample.empty:
                first_val = str(sample.iloc[0])
                # Basic heuristic to avoid parsing arbitrary strings/IDs as dates
                if '-' in first_val or '/' in first_val or ':' in first_val:
                    try:
                        parsed = pd.to_datetime(df[col], errors='raise')
                        if pd.api.types.is_datetime64_any_dtype(parsed):
                            df[col] = parsed
                    except Exception:
                        pass # leave as string if parsing fails
        
        # Detect type category
        if pd.api.types.is_bool_dtype(df[col]):
            col_type = "boolean"
        elif pd.api.types.is_datetime64_any_dtype(df[col]):
            col_type = "date"
        elif pd.api.types.is_numeric_dtype(df[col]):
            col_type = "numeric"
        else:
            col_type = "string"

        schema["columns"].append({
            "name": col,
            "type": col_type
        })

    # 4. Store dataframe in SQLite table
    db_dir = os.path.dirname(os.path.abspath(db_path))
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)
        
    conn = sqlite3.connect(db_path)
    df.to_sql(table_name, conn, if_exists='replace', index=False)
    conn.close()

    return schema

if __name__ == "__main__":
    env = Path(r"C:\Users\hp\Desktop\Chat-Report Generation\Backend\.env")
    load_dotenv(env)
    path = os.getenv("CSV_PATH")
    
    if path and os.path.exists(path):
        print(f"Reading CSV from {path}...")
        df = pd.read_csv(path)
        
        # Save db in the Backend directory
        db_path = Path(__file__).parent / "data.db"
        
        schema = process_and_store_data(df, db_path=str(db_path), table_name="data")
        
        print("\n=== Extracted Schema ===")
        print(json.dumps(schema, indent=2))
        print(f"\nData successfully stored in {db_path} under table 'data'.")
    else:
        print("CSV_PATH is either not set in .env or the file does not exist.")