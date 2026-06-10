"""
kaggle/src/data_loader.py — Download & load airline data.
"""
import os
import sys
import warnings
warnings.filterwarnings("ignore")

try:
    import cudf.pandas
    cudf.pandas.install()
    print("[data_loader] RAPIDS cuDF pandas acceleration enabled.")
except ImportError:
    pass

import gdown
import zipfile
import pandas as pd

# Project root is two levels up from kaggle/src/
_KAGGLE_DIR  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # kaggle/
_PROJECT_ROOT = os.path.dirname(_KAGGLE_DIR)                                 # project root/
sys.path.insert(0, _PROJECT_ROOT)

from kaggle.src.config import (
    GDRIVE_FILE_ID, USE_DIRECT_UPLOAD,
    DATA_DIR,
)


def find_csv_files(directory: str) -> list:
    csv_files = []
    for root, _, files in os.walk(directory):
        for f in files:
            if f.endswith(".csv") and not f.startswith("~"):
                csv_files.append(os.path.join(root, f))
    return sorted(csv_files)


def download_from_gdrive() -> str:
    print("[data_loader] Downloading data from Google Drive...")
    
    # Determine working/data directory dynamically to handle cross-platform (local Windows vs Kaggle environment)
    if os.path.exists("/kaggle/working"):
        working_dir = "/kaggle/working"
    else:
        working_dir = os.path.join(_PROJECT_ROOT, "data")
        
    os.makedirs(working_dir, exist_ok=True)
    zip_path = os.path.join(working_dir, "data.zip")
    
    url = f"https://drive.google.com/uc?id={GDRIVE_FILE_ID}"
    gdown.download(url, zip_path, quiet=False)

    size_mb = os.path.getsize(zip_path) / 1024 / 1024
    print(f"[data_loader] Downloaded {size_mb:.2f} MB -> {zip_path}")

    print("[data_loader] Extracting...")
    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(working_dir)
        files = z.namelist()
        print(f"[data_loader] Extracted {len(files)} files:")
        for f in files[:10]:
            print(f"         - {f}")
        if len(files) > 10:
            print(f"         ... and {len(files) - 10} more")

    return os.path.join(working_dir, "AI_hackathon")


def load_all_csv(directory: str) -> pd.DataFrame:
    csv_files = find_csv_files(directory)

    if not csv_files:
        raise FileNotFoundError(f"No CSV files found in {directory}")

    print(f"[data_loader] Found {len(csv_files)} CSV files:")
    for f in csv_files[:10]:
        print(f"           - {os.path.basename(f)}")
    if len(csv_files) > 10:
        print(f"           ... and {len(csv_files) - 10} more")

    dfs = []
    for f in csv_files:
        try:
            df_chunk = pd.read_csv(f, low_memory=False)
            print(f"           {os.path.basename(f)}: {len(df_chunk):,} rows")
            dfs.append(df_chunk)
        except Exception as e:
            print(f"           WARNING: Failed to read {f}: {e}")

    if not dfs:
        raise ValueError("No CSV files could be loaded")

    df = pd.concat(dfs, ignore_index=True)
    print(f"[data_loader] Combined: {len(df):,} rows x {df.shape[1]} cols")
    return df


def load() -> pd.DataFrame:
    candidates = [
        DATA_DIR,
        "/kaggle/working/AI_hackathon",
        "/kaggle/input/AI_hackathon",
        "/kaggle/input",
        "data",
    ]

    if USE_DIRECT_UPLOAD:
        print("[data_loader] Using directly uploaded file")
        for candidate in ["/kaggle/input"]:
            if os.path.exists(candidate):
                csvs = find_csv_files(candidate)
                if csvs:
                    return load_all_csv(candidate)
        raise FileNotFoundError("USE_DIRECT_UPLOAD=True but no data found")

    if GDRIVE_FILE_ID:
        data_dir = download_from_gdrive()
        return load_all_csv(data_dir)

    for candidate in candidates:
        if os.path.exists(candidate):
            csvs = find_csv_files(candidate)
            if csvs:
                return load_all_csv(candidate)

    raise FileNotFoundError(
        f"No data found. Please set GDRIVE_FILE_ID or set USE_DIRECT_UPLOAD=True"
    )


if __name__ == "__main__":
    df = load()
    print(f"\nDataset shape: {df.shape}")
    print(f"Columns: {df.columns.tolist()}")
