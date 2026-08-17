from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path

import numpy as np

from ..config import ROOT_DIR
from .forecast_types import ForecastResult

logger = logging.getLogger(__name__)

FIN_ROOT = ROOT_DIR / "timesfm_fin"
INFER_SCRIPT = FIN_ROOT / "infer.py"
JSON_RESULT_PREFIX = "TIMESFM_FIN_RESULT:"


def _fin_python() -> str:
    explicit = os.getenv("TIMESFM_FIN_PYTHON")
    if explicit:
        return explicit
    venv_python = FIN_ROOT / ".venv" / "bin" / "python"
    if venv_python.exists():
        return str(venv_python)
    return "python3.10"


def is_fin_available() -> bool:
    if not INFER_SCRIPT.exists():
        return False
    fin_py = Path(_fin_python())
    return fin_py.exists()


def _parse_subprocess_result(stdout_bytes: bytes, stderr_text: str) -> dict:
    stdout_text = stdout_bytes.decode("utf-8", errors="replace").strip()
    if stdout_text:
        try:
            return json.loads(stdout_text)
        except json.JSONDecodeError:
            for line in reversed(stdout_text.splitlines()):
                stripped = line.strip()
                if stripped.startswith("{"):
                    return json.loads(stripped)

    for line in reversed(stderr_text.splitlines()):
        if line.startswith(JSON_RESULT_PREFIX):
            return json.loads(line[len(JSON_RESULT_PREFIX) :])

    preview = stdout_text[:500] if stdout_text else "(empty)"
    raise RuntimeError(f"TimesFM-Fin produced no parseable JSON. stdout={preview!r}")


async def _pipe_stderr_to_logger(stream: asyncio.StreamReader) -> str:
    lines: list[str] = []
    while True:
        chunk = await stream.readline()
        if not chunk:
            break
        text = chunk.decode("utf-8", errors="replace").rstrip()
        if text:
            lines.append(text)
            if text.startswith(JSON_RESULT_PREFIX):
                logger.info("[timesfm-fin] result payload received (%d bytes)", len(text))
            else:
                logger.info("[timesfm-fin] %s", text)
    return "\n".join(lines)


async def run_forecast(
    closes: np.ndarray,
    horizon: int,
    interval: str,
) -> ForecastResult:
    if not INFER_SCRIPT.exists():
        raise RuntimeError(
            f"TimesFM-Fin infer script missing at {INFER_SCRIPT}. "
            "See timesfm_fin/README.md to set up the Python 3.10 environment."
        )

    if len(closes) < 32:
        raise ValueError("TimesFM-Fin requires at least 32 historical points")

    horizon = min(int(horizon), 128)
    payload = {
        "closes": closes.astype(float).tolist(),
        "horizon": horizon,
        "interval": interval,
        "repo_id": os.getenv("TIMESFM_FIN_REPO_ID", "pfnet/timesfm-1.0-200m-fin"),
        "checkpoint_path": os.getenv("TIMESFM_FIN_CHECKPOINT_PATH"),
        "backend": os.getenv("TIMESFM_FIN_BACKEND", "cpu"),
    }

    env = os.environ.copy()
    env.setdefault("CUDA_VISIBLE_DEVICES", "")
    env.setdefault("JAX_PLATFORMS", "cpu")
    env.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
    env.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "0")

    python_bin = _fin_python()
    logger.info(
        "Starting TimesFM-Fin subprocess: python=%s repo=%s backend=%s",
        python_bin,
        payload["repo_id"],
        payload["backend"],
    )

    proc = await asyncio.create_subprocess_exec(
        python_bin,
        "-u",
        str(INFER_SCRIPT),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(FIN_ROOT),
        env=env,
    )

    stderr_task = asyncio.create_task(_pipe_stderr_to_logger(proc.stderr))

    assert proc.stdin is not None
    proc.stdin.write(json.dumps(payload).encode("utf-8"))
    await proc.stdin.drain()
    proc.stdin.close()

    stdout_bytes = await proc.stdout.read() if proc.stdout else b""
    stderr_text = await stderr_task
    return_code = await proc.wait()

    if return_code != 0:
        stdout_text = stdout_bytes.decode("utf-8", errors="replace").strip()
        err = stderr_text.strip() or stdout_text or f"exit code {return_code}"
        logger.error("TimesFM-Fin subprocess failed (code=%s)", return_code)
        raise RuntimeError(f"TimesFM-Fin subprocess failed: {err}")

    data = _parse_subprocess_result(stdout_bytes, stderr_text)
    logger.info(
        "TimesFM-Fin success: horizon=%s device=%s source=%s",
        data.get("horizon"),
        data.get("device"),
        data.get("weight_source"),
    )
    return ForecastResult(
        median=data["median"],
        lower=data["lower"],
        upper=data["upper"],
        context_length=int(data["context_length"]),
        horizon=int(data["horizon"]),
        device=str(data.get("device", "cpu")),
        model="timesfm-fin",
        model_label="TimesFM-Fin (PFN financial fine-tune)",
    )
