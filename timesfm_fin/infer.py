from __future__ import annotations

import contextlib
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

# Preserve fd 1 for JSON IPC; timesfm prints to stdout on import/forecast.
_RESULT_OUT = os.fdopen(os.dup(1), "w", closefd=False)
JSON_RESULT_PREFIX = "TIMESFM_FIN_RESULT:"

# Force CPU before JAX/tensorflow initialize
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")
os.environ.setdefault("JAX_PLATFORMS", "cpu")

CONTEXT_LEN = 512
MAX_HORIZON = 128
PLUS_ONE = True
USE_LOG = True

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [timesfm-fin] %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stderr,
    force=True,
)
log = logging.getLogger("timesfm-fin")


@contextlib.contextmanager
def _stdout_to_stderr():
    """Route third-party print() away from the JSON stdout channel."""
    prev = sys.stdout
    sys.stdout = sys.stderr
    try:
        yield
    finally:
        sys.stdout = prev


def _emit_result(result: dict[str, Any]) -> None:
    payload = json.dumps(result)
    _RESULT_OUT.write(payload + "\n")
    _RESULT_OUT.flush()
    print(f"{JSON_RESULT_PREFIX}{payload}", file=sys.stderr, flush=True)


def _log_hf_cache_status(repo_id: str) -> None:
    try:
        from huggingface_hub import scan_cache_dir, try_to_load_from_cache

        marker = "checkpoints/checkpoint_6101/state/checkpoint"
        cached = try_to_load_from_cache(repo_id, marker)
        if cached and Path(cached).is_file():
            size_mb = Path(cached).stat().st_size / (1024 * 1024)
            log.info("HF weights cached: %s (%.1f MB)", cached, size_mb)
            return

        log.info("HF weights not in local cache yet for %s", repo_id)
        log.info("Will download via snapshot_download on first load (~1.6 GB, several minutes)")
        try:
            cache_info = scan_cache_dir()
            for repo in cache_info.repos:
                if repo.repo_id == repo_id:
                    log.info("Partial HF cache entry found: %s", repo.repo_path)
                    return
        except Exception:
            pass
    except ImportError:
        log.warning("huggingface_hub not available for cache inspection")


def _freq_for_interval(interval: str) -> int:
    if interval == "daily":
        return 0
    if interval in ("weekly", "monthly"):
        return 1
    return 0


def _build_model(repo_id: str, checkpoint_path: str | None, backend: str):
    with _stdout_to_stderr():
        import timesfm

        backend = "cpu" if backend != "gpu" else backend

        hparams = timesfm.TimesFmHparams(
            backend=backend,
            context_len=CONTEXT_LEN,
            horizon_len=MAX_HORIZON,
            input_patch_len=32,
            output_patch_len=128,
            num_layers=20,
            model_dims=1280,
            per_core_batch_size=1,
        )

        if checkpoint_path:
            log.info("Loading checkpoint from local path: %s", checkpoint_path)
            checkpoint = timesfm.TimesFmCheckpoint(path=checkpoint_path)
            source = checkpoint_path
        else:
            log.info("Loading checkpoint from Hugging Face repo: %s", repo_id)
            _log_hf_cache_status(repo_id)
            checkpoint = timesfm.TimesFmCheckpoint(huggingface_repo_id=repo_id)
            source = repo_id

        log.info("Initializing TimesFM JAX model (backend=%s)...", backend)
        t0 = time.perf_counter()
        tfm = timesfm.TimesFm(hparams=hparams, checkpoint=checkpoint)
        log.info(
            "Model ready in %.1fs (checkpoint restored + decode jitted)",
            time.perf_counter() - t0,
        )
    return tfm, source, backend


def _extract_bands(
    mean: np.ndarray,
    full: np.ndarray | None,
    horizon: int,
) -> tuple[list[float], list[float], list[float]]:
    median = mean[0, :horizon].astype(float).tolist()
    lower = median[:]
    upper = median[:]

    if full is None:
        return median, lower, upper

    row = full[0, :horizon, :]
    if row.ndim == 2 and row.shape[1] >= 10:
        lower = row[:, 1].astype(float).tolist()
        upper = row[:, 9].astype(float).tolist()
    elif row.ndim == 2 and row.shape[1] >= 3:
        lower = row[:, 0].astype(float).tolist()
        upper = row[:, -1].astype(float).tolist()

    return median, lower, upper


def run(payload: dict[str, Any]) -> dict[str, Any]:
    closes = np.asarray(payload["closes"], dtype=np.float64)
    horizon = min(int(payload.get("horizon", 20)), MAX_HORIZON)
    interval = str(payload.get("interval", "daily"))
    repo_id = payload.get("repo_id") or "pfnet/timesfm-1.0-200m-fin"
    checkpoint_path = payload.get("checkpoint_path")
    backend = str(payload.get("backend") or "cpu").lower()

    log.info(
        "Inference start: bars=%d context=%d horizon=%d interval=%s",
        len(closes),
        min(len(closes), CONTEXT_LEN),
        horizon,
        interval,
    )

    if len(closes) < 32:
        raise ValueError("Need at least 32 close prices")

    context = closes[-CONTEXT_LEN:].astype(np.float64)
    log.info("Preprocess: plus_one=%s log_transform=%s", PLUS_ONE, USE_LOG)

    if PLUS_ONE:
        context = context + 1.0
    if USE_LOG:
        context = np.log(context)

    tfm, source, device = _build_model(repo_id, checkpoint_path, backend)

    freq_value = _freq_for_interval(interval)
    log.info("Running forecast (freq=%d)...", freq_value)
    t0 = time.perf_counter()
    with _stdout_to_stderr():
        mean, full = tfm.forecast([context], freq=[freq_value])
    log.info("Forecast done in %.1fs", time.perf_counter() - t0)

    mean = np.asarray(mean, dtype=np.float64)
    full_arr = np.asarray(full, dtype=np.float64) if full is not None else None

    if USE_LOG:
        mean = np.exp(mean)
        if full_arr is not None:
            full_arr = np.exp(full_arr)
    if PLUS_ONE:
        mean = mean - 1.0
        if full_arr is not None:
            full_arr = full_arr - 1.0

    median, lower, upper = _extract_bands(mean, full_arr, horizon)
    log.info("Done. median[0]=%.4f weight_source=%s", median[0] if median else 0, source)

    return {
        "median": median,
        "lower": lower,
        "upper": upper,
        "context_length": len(context),
        "horizon": horizon,
        "device": device,
        "model": "timesfm-fin",
        "model_label": "TimesFM-Fin (PFN financial fine-tune)",
        "weight_source": source,
        "preprocess": {"plus_one": PLUS_ONE, "log": USE_LOG},
    }


def main() -> None:
    raw = sys.stdin.read()
    payload = json.loads(raw) if raw.strip() else {}
    result = run(payload)
    _emit_result(result)


if __name__ == "__main__":
    main()
