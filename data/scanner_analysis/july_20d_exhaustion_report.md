# July 20D Pre-Return Exhaustion Study

Generated: 2026-08-14T21:39:10.981921+00:00
Scope: 2026-07-01 → 2026-07-31 (quality_v1). Triggered n=373.

## Baseline (triggered, no extra 20d cap)
- T+5:  n=373 WR=52.28% avg=0.586 med=0.2829 PF=1.314 FP=47.72%
- T+10: n=364 WR=55.22% avg=1.2671 med=0.858 PF=1.512 FP=44.78%
- T+20: n=204 WR=53.92% avg=1.8774 med=1.0995 PF=1.498 FP=46.08%

## By prior 20D run-up bucket (triggered)
| Bucket | n | T+5 WR | T+5 avg | T+10 WR | T+10 avg | T+20 WR | T+20 avg |
|--------|---|--------|---------|---------|----------|---------|----------|
| <0% | 28 | 64.29 | 1.9323 | 55.56 | 1.9433 | 75.0 | 3.8504 |
| 0–10% | 129 | 55.04 | 0.5651 | 63.71 | 1.5423 | 67.24 | 3.449 |
| 10–15% | 70 | 52.86 | 0.2264 | 51.43 | 1.9389 | 53.19 | 3.7366 |
| 15–20% | 67 | 47.76 | 0.5649 | 58.46 | 1.7042 | 45.71 | 1.8289 |
| 20–25% | 33 | 36.36 | -1.3036 | 33.33 | -3.057 | 34.78 | -2.707 |
| 25–35% | 46 | 54.35 | 1.7587 | 48.89 | 1.5976 | 44.83 | -1.4006 |
| 35–50% | 0 | None | None | None | None | None | None |
| >50% | 0 | None | None | None | None | None | None |

## Optimal cap: **18%**

### Baseline vs filtered (triggered)
| Set | n | ret% | T+5 WR/avg | T+10 WR/avg | T+20 WR/avg |
|-----|---|------|------------|-------------|-------------|
| Baseline | 373 | 100 | 52.28/0.586 | 55.22/1.2671 | 53.92/1.8774 |
| Hard ≤18% | 270 | 72.39 | 54.44/0.7078 | 58.94/1.8287 | 59.71/3.5484 |
| ≤18% or higher-low | 362 | 97.05 | 53.04/0.7108 | 55.81/1.4343 | 54.77/2.0771 |

## Recommendation
- Implement `MAX_20D_RUNUP_PCT = 18` hard gate on **triggered** alerts.
- Exception: allow above-cap triggers that still print a **higher low** (10d vs prior 10d).

JSON: `/root/self_projects/trading/data/scanner_analysis/july_20d_exhaustion_report.json`
