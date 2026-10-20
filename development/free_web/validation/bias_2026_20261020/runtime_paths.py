"""Paths for a checked-out repository or an explicitly configured cloud workspace."""
from pathlib import Path
import os
ROOT=Path(os.environ.get('JRA_BIAS_WORKDIR','bias_20261020'))
candidates=[Path(os.environ['JRA_MODULE_DIR'])] if os.environ.get('JRA_MODULE_DIR') else []
candidates += [Path(__file__).resolve().parents[2],Path.cwd()/'development/free_web',
               Path.cwd()/'repair_20261020/repo/development/free_web']
MODULES=next((p.resolve() for p in candidates if (p/'infer_free_model.py').is_file()),None)
if MODULES is None:raise RuntimeError('Set JRA_MODULE_DIR to the saved free_web module directory')
ASSETS=ROOT/'private_assets'
MODEL=Path(os.environ.get('JRA_MODEL_DIR',str(ASSETS/'JRA_free_model_52_20261013')))
HISTORY_DIR=Path(os.environ.get('JRA_HISTORY_DIR',str(ASSETS/'JRA_free_history_20261012')))
HISTORY=HISTORY_DIR/'history.parquet'
BUNDLE=Path(os.environ.get('JRA_BUNDLE_DIR',str(ASSETS/'JRA_preflight_bundle_20261013')))
