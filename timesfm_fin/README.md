# TimesFM-Fin (Preferred Networks)

Financial fine-tune of **TimesFM 1.0 200M**, published by [Preferred Networks](https://tech.preferred.jp/en/blog/timesfm/).

- GitHub: [pfnet-research/timesfm_fin](https://github.com/pfnet-research/timesfm_fin)
- Weights: [pfnet/timesfm-1.0-200m-fin](https://huggingface.co/pfnet/timesfm-1.0-200m-fin)

## How PFN structured the Hugging Face release

The HF repo does **not** ship a standalone `pytorch_model.bin` meant for `TimesFmCheckpoint(huggingface_repo_id=...)` on the PyTorch backend.

Instead it mirrors Google's **JAX/PAX checkpoint layout**:

```
checkpoints/checkpoint_6101/
  metadata/
  state/
```

Weights load through the native **TimesFM 1.x** API:

```python
import timesfm

tfm = timesfm.TimesFm(
    context_len=512,
    horizon_len=128,
    input_patch_len=32,
    output_patch_len=128,
    num_layers=20,
    model_dims=1280,
    backend="cpu",  # or "gpu"
)
tfm.load_from_checkpoint(repo_id="pfnet/timesfm-1.0-200m-fin")
```

This is continual pre-training on top of Google's TimesFM 1.0 architecture — the same loader used in [timesfm_fin/src/main.py](https://github.com/pfnet-research/timesfm_fin/blob/master/src/main.py) and [mock_trading.py](https://github.com/pfnet-research/timesfm_fin/blob/master/src/mock_trading.py).

### Inference preprocessing (from PFN blog)

1. Take last **512** close prices
2. Optional **+1** offset
3. **Log transform**: `y ← log(y)`
4. Forecast, then invert: `exp()` and `-1`

Frequency indicator for TimesFM 1.0:

| Interval | `freq` |
|----------|--------|
| Daily | 0 |
| Weekly / Monthly | 1 |

## Setup (isolated Python 3.10 env)

TimesFM-Fin requires **Python 3.10** and the JAX-oriented `timesfm==1.2.0` package — separate from the main backend's TimesFM **2.5 PyTorch** stack (Python 3.11+).

```bash
cd timesfm_fin
chmod +x setup.sh
./setup.sh
```

Add to `trading/.env`:

```env
FORECAST_MODEL=timesfm-fin
TIMESFM_FIN_PYTHON=/root/self_projects/trading/timesfm_fin/.venv/bin/python
# optional overrides:
# TIMESFM_FIN_REPO_ID=pfnet/timesfm-1.0-200m-fin
# TIMESFM_FIN_CHECKPOINT_PATH=/path/to/local/checkpoints
# TIMESFM_FIN_BACKEND=cpu
```

## Standalone test

```bash
echo '{"closes":[100,101,102,103,104,105,106,107,108,109,110,111,112,113,114,115,116,117,118,119,120,121,122,123,124,125,126,127,128,129,130,131],"horizon":5,"interval":"daily"}' \
  | timesfm_fin/.venv/bin/python timesfm_fin/infer.py
```

## Integration with trading app

The FastAPI backend dispatches forecasts via `forecast_registry.py`:

| Model ID | Engine | Env |
|----------|--------|-----|
| `timesfm-2.5` (default) | In-process PyTorch 2.5 | Main backend venv |
| `timesfm-fin` | Subprocess → `infer.py` | Python 3.10 venv here |

Switch in UI or API:

```
GET /api/forecast?symbol=RELIANCE&interval=daily&model=timesfm-fin
GET /api/models
```

## Notes

- **License:** CC BY-NC-SA 4.0 — verify compliance for your use case
- **NSE coverage:** Model trained on S&P500, TOPIX500, crypto, forex — Nifty 50 is out-of-sample
- **RAM:** JAX checkpoint restore typically needs 16GB+ RAM on first load
- **Horizon cap:** 128 steps for fin model (UI daily/weekly/monthly horizons are below this)

See also [FEASIBILITY.md](./FEASIBILITY.md) for the original gap analysis (updated below).
