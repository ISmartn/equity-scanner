#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

PY="${PYTHON_310:-python3.10}"
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "Python 3.10 is required. Install it or set PYTHON_310=/path/to/python3.10"
  exit 1
fi

if command -v uv >/dev/null 2>&1; then
  echo "Using uv..."
  uv venv --python 3.10 .venv
  uv pip install --python .venv/bin/python -r requirements.txt
else
  echo "Using pip..."
  "$PY" -m venv .venv
  .venv/bin/pip install --upgrade pip
  .venv/bin/pip install -r requirements.txt
fi

echo ""
echo "Verifying imports..."
.venv/bin/python -c "import jax; import jaxlib; import timesfm; print('OK: jax', jax.__version__, 'jaxlib', jaxlib.__version__)"

echo ""
echo "TimesFM-Fin ready. Add to trading/.env:"
echo "  FORECAST_MODEL=timesfm-fin"
echo "  TIMESFM_FIN_PYTHON=$ROOT/.venv/bin/python"
