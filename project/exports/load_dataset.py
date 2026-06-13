import pandas as pd
import pyarrow.parquet as pq
import json
from pathlib import Path


def load_table(table_name, exports_dir="."):
    exports_dir = Path(exports_dir)
    manifest = exports_dir / f"{table_name}_manifest.json"
    if manifest.exists():
        m = json.loads(manifest.read_text())
        return pd.concat(
            [pd.read_parquet(exports_dir / p) for p in m["parts"]],
            ignore_index=True,
        )
    return pd.read_parquet(exports_dir / f"{table_name}.parquet")
