# TimesFM-Fin Integration — Updated Assessment

**Previous status:** NOT READY (looked for PyTorch `.ckpt` files)  
**Current status:** IMPLEMENTABLE via JAX `TimesFm.load_from_checkpoint(repo_id=...)`

## Correction: weights are not missing

PFN's [pfnet/timesfm-1.0-200m-fin](https://huggingface.co/pfnet/timesfm-1.0-200m-fin) uses the **native TimesFM 1.x JAX checkpoint layout**, identical to Google's releases:

```
checkpoints/checkpoint_6101/metadata/
checkpoints/checkpoint_6101/state/
```

Loading (from [timesfm_fin/src/main.py](https://github.com/pfnet-research/timesfm_fin/blob/master/src/main.py)):

```python
tfm = timesfm.TimesFm(context_len=512, horizon_len=128, ...)
tfm.load_from_checkpoint(repo_id="pfnet/timesfm-1.0-200m-fin")
```

The HuggingFace discussion about missing `torch_model.ckpt` applies only when using the **PyTorch backend** — wrong backend for this release.

---

## Original analysis (partially superseded)

**Status at first review:** NOT READY TO IMPLEMENT  
**Sources reviewed:**
- [Preferred Networks blog](https://tech.preferred.jp/en/blog/timesfm/)
- [pfnet-research/timesfm_fin](https://github.com/pfnet-research/timesfm_fin)
- [pfnet/timesfm-1.0-200m-fin (HuggingFace)](https://huggingface.co/pfnet/timesfm-1.0-200m-fin)
- [HF Discussion #1 — loading failure](https://huggingface.co/pfnet/timesfm-1.0-200m-fin/discussions/1)
- Current trading app: `backend/app/services/timesfm_service.py` (TimesFM **2.5** PyTorch)

---

## What you asked for

A new module that lets you switch between:

| Mode | Model |
|------|-------|
| **Current** | Google TimesFM 2.5 200M PyTorch (`google/timesfm-2.5-200m-pytorch`) |
| **Fin** | PFN fine-tuned TimesFM 1.0 200M for financial data (`pfnet/timesfm-1.0-200m-fin`) |

---

## What IS documented (sufficient)

### Methodology (blog + repo)

From the [Preferred Networks article](https://tech.preferred.jp/en/blog/timesfm/):

- Fine-tune **TimesFM 1.0 200M** on financial OHLCV (S&P500, TOPIX500, crypto, forex, etc.)
- **Log transform** at train/inference: `y ← log(y)`; invert with `exp()` at output
- Optional **+1 offset** before log (handled in repo code)
- **Context length:** 512 (fixed at inference)
- **Max horizon:** 128
- **Architecture:** 20 layers, 1280 dims, patch 32/128
- Frequency indicator: `0` = daily, `1` = weekly/monthly, `2` = quarterly/yearly

### Inference pattern (from `mock_trading.py`)

```python
tfm = timesfm.TimesFm(
    context_len=512,
    horizon_len=128,
    input_patch_len=32,
    output_patch_len=128,
    num_layers=20,
    model_dims=1280,
    backend="gpu",  # or "cpu"
)
tfm.load_from_checkpoint(checkpoint_path)  # LOCAL path, not HF repo_id

# Preprocess
input_ts = last_512_closes
if plus_one: input_ts += 1
if use_log:  input_ts = log(input_ts)

predictions, quantiles = tfm.forecast(input_ts, freq=zeros)

# Postprocess
if use_log:  predictions = exp(predictions)
if plus_one: predictions -= 1
```

### Published artifacts

- Training/fine-tuning code: [timesfm_fin/src](https://github.com/pfnet-research/timesfm_fin/tree/master/src)
- Weights on HF: [pfnet/timesfm-1.0-200m-fin](https://huggingface.co/pfnet/timesfm-1.0-200m-fin)
- License: **CC BY-NC-SA 4.0** (non-commercial — check compliance for your use case)

---

## Implementation (done)

See [README.md](./README.md). The trading app switches models via:

- `FORECAST_MODEL=timesfm-2.5|timesfm-fin`
- `GET /api/forecast?model=timesfm-fin`
- UI model picker in sidebar

TimesFM-Fin runs in an isolated **Python 3.10 subprocess** because it cannot share a venv with TimesFM 2.5 PyTorch.

---

## Original blockers (revised)

### 1. ~~HuggingFace weights cannot be loaded~~ → RESOLVED

Use JAX `load_from_checkpoint(repo_id="pfnet/timesfm-1.0-200m-fin")`, not PyTorch `TimesFmCheckpoint`.

### 2. Different model generation — STILL APPLIES

The HF repo stores **JAX/PAX training checkpoints**:

```
checkpoints/checkpoint_6101/
  metadata/
  state/
```

There is **no** `torch_model.ckpt`, and the PyTorch loader fails. An open HF discussion from April 2025 reports:

> `OSError: No such file or directory: ... torch_model.ckpt`

The discussion has **no official PFN response** with working load code as of mid-2025. Users are still blocked.

`mock_trading.py` uses `load_from_checkpoint(checkpoint_path)` with a **local directory** produced by their training pipeline — not documented for HF download.

### 2. Different model generation than our current app

| | Current trading app | timesfm_fin |
|--|---------------------|-------------|
| Model | TimesFM **2.5** | TimesFM **1.0** |
| API | `TimesFM_2p5_200M_torch.from_pretrained()` | `timesfm.TimesFm()` |
| Backend | PyTorch | JAX (training) / mixed for inference |
| Package | `timesfm[torch]>=1.2` | `pip install timesfm` (old v1 API) |
| Context | up to 1024 | 512 |
| Quantiles | Continuous quantile head (2.5) | Experimental / not calibrated (1.0) |

These are **not drop-in interchangeable**. A config flag cannot switch between them in one process without:

- Pinning two incompatible `timesfm` package versions, or
- Running two separate inference services

### 3. Python / dependency conflict

timesfm_fin README states:

> The `timesfm` package can only be installed in **Python 3.10** due to package conflicts.

Training/evaluation additionally requires:

- `jax`, `flax`, `praxis`, `paxml`, `tensorflow`, `clu`, `optax`

None of this is in our current `backend/requirements.txt`. The training stack is heavy and separate from our FastAPI PyTorch path.

### 4. No NSE / Nifty-specific fine-tuning

PFN trained on S&P500, TOPIX500, currencies, crypto — **not Indian equities**.

Blog Table 10 shows fin model Sharpe on S&P500 = 1.68 vs original TimesFM 0.42, but on currencies it **underperforms AR(1)**. Applying this checkpoint to Nifty 50 is out-of-distribution extrapolation; no published weights or eval exist for NSE.

### 5. No fine-tuning dataset

README explicitly states:

> The fine-tuning dataset is **proprietary and not publicly available**.

We cannot reproduce or fine-tune on NSE data using their pipeline without building our own dataset and training infra (8× V100 per their blog).

### 6. UI uncertainty bands unclear for fin model

Our UI shows 80% quantile bands from TimesFM 2.5's continuous quantile head.

TimesFM 1.0 docs note quantile heads are **experimental and not calibrated**. The fin repo returns `quantiles` from `forecast()` but mock trading only uses point predictions for direction — no documented band mapping for production UI.

### 7. Weekly/monthly handling differs

Blog recommends freq `1` for weekly/monthly. Our app resamples to weekly/monthly bars then forecasts — compatible in theory, but fin model was primarily evaluated on **daily** data with 512-day context.

---

## Gap summary

| Requirement | Available? |
|-------------|------------|
| Inference algorithm (log transform, 512 context) | ✅ Yes |
| Hyperparameters | ✅ Yes |
| Mock trading reference code | ✅ Yes |
| Load HF weights in PyTorch / current timesfm | ❌ No (broken, unresolved) |
| Load HF weights in JAX without full paxml stack | ❌ Not documented |
| Compatible with TimesFM 2.5 in same app | ❌ No |
| Nifty 50 / NSE validation | ❌ No |
| Quantile bands for UI | ⚠️ Unclear |
| Fine-tune on our data | ❌ No public dataset |

---

## Recommendation

**Do not implement a configurable switch yet.** The published artifacts are insufficient for a reliable integration into the current trading stack.

### Minimum prerequisites before implementation

1. **Working weight loader** — PFN or community documents how to load `pfnet/timesfm-1.0-200m-fin` from HuggingFace into a runnable inference API (PyTorch or JAX). Until [HF Discussion #1](https://huggingface.co/pfnet/timesfm-1.0-200m-fin/discussions/1) is resolved, this is blocked.

2. **Separate inference service** — Run TimesFM 1.0 fin in an isolated Python 3.10 + JAX environment (subprocess or Docker), not in-process with TimesFM 2.5 PyTorch.

3. **Validate on NSE** — Backtest fin model on Nifty 50 daily data; compare vs zero-shot 2.5 before exposing in UI.

4. **Clarify quantile output** — Decide if UI shows point-only for fin mode or derive bands another way.

### Alternative paths (when ready)

| Path | Effort | Notes |
|------|--------|-------|
| **A. Wait for PFN PyTorch export** | Low (once available) | Best if they publish `torch_model.ckpt` |
| **B. Sidecar JAX service** | High | Clone timesfm_fin, download PAX ckpt, wrap `mock_trading` logic as API |
| **C. Fine-tune ourselves** | Very high | Use Upstox/NSE 5Y data + timesfm_fin training code; needs GPU cluster |
| **D. Keep TimesFM 2.5 + log preprocess only** | Low | Apply blog's log transform to 2.5 inputs (partial methodology, not fin weights) |

---

## If implementation is approved later

Suggested folder layout (not created yet):

```
trading/timesfm_fin/
├── README.md              # this file
├── docker/
│   └── Dockerfile.py310   # isolated JAX + timesfm v1 env
├── scripts/
│   └── download_checkpoint.py
├── inference/
│   └── fin_forecast.py    # log transform + TimesFm 1.0 wrapper
└── INTEGRATION.md         # how backend MODEL_PROVIDER=fin|2.5 routes requests
```

Backend would add:

```env
FORECAST_MODEL=timesfm-2.5   # or timesfm-fin
TIMESFM_FIN_CHECKPOINT=/path/to/checkpoint_6101
```

Frontend would add a model selector dropdown.

---

## Conclusion

The blog and GitHub repo explain **how PFN fine-tuned TimesFM** and provide training/mock-trading code, but they do **not** provide everything needed to plug `timesfm_fin` into our existing TimesFM 2.5 PyTorch app with a config switch. The critical missing piece is a **documented, working path to load published HuggingFace weights for inference** in a stack compatible with our backend.

**Per your instruction: implementation is deferred until those gaps are closed.**
