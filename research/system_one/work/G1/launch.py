"""run_job.sh starts the workspace's Python 3.10; the decision models need 3.12. Hand over to venv_g1, keeping the
environment (CUDA_VISIBLE_DEVICES, HF_HOME) that run_job.sh set."""
import os
import sys
from pathlib import Path

ws = Path(os.environ.get("ORDERGUARD_WORKSPACE", Path(__file__).resolve().parents[2]))
py = ws / "venv_g1" / "bin" / "python"
os.environ.setdefault("HF_HUB_ENABLE_HF_TRANSFER", "1")
os.execv(str(py), [str(py), str(Path(__file__).with_name("gpu_readers.py")), *sys.argv[1:]])
