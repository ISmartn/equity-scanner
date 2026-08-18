#!/usr/bin/env python3
"""Smoke-test x-tweet-fetcher backends and write results to out/."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "out"
XTF = ROOT / ".venv" / "bin" / "xtf"

# Sample public tweet for FxTwitter single-tweet smoke test
SAMPLE_TWEET = "https://x.com/kyalashish/status/2089286346661847542?s=48"


def run_xtf(args: list[str], timeout: int = 45) -> dict:
    cmd = [str(XTF), *args, "--pretty", "--lang", "en"]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=ROOT,
    )
    payload: dict = {
        "cmd": cmd,
        "returncode": proc.returncode,
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
    }
    if proc.stdout.strip():
        try:
            payload["json"] = json.loads(proc.stdout)
        except json.JSONDecodeError:
            payload["json"] = None
    else:
        payload["json"] = None
    return payload


def summarize(name: str, result: dict) -> dict:
    data = result.get("json") or {}
    ok = result["returncode"] == 0 and not data.get("error") and not data.get("error_code")
    summary = {
        "name": name,
        "ok": ok,
        "returncode": result["returncode"],
        "error": data.get("error") if isinstance(data, dict) else None,
        "error_code": data.get("error_code") if isinstance(data, dict) else None,
        "error_causes": data.get("error_causes") if isinstance(data, dict) else None,
    }
    if isinstance(data, dict) and "text" in data:
        summary["text_preview"] = str(data.get("text") or "")[:160]
    if isinstance(data, list):
        summary["count"] = len(data)
    if isinstance(data, dict) and isinstance(data.get("tweets"), list):
        summary["count"] = len(data["tweets"])
    return summary


def main() -> int:
    if not XTF.exists():
        print(f"Missing xtf binary at {XTF}. Run setup first.", file=sys.stderr)
        return 2

    OUT.mkdir(parents=True, exist_ok=True)
    cases = [
        ("single_tweet_fxtwitter", ["--url", SAMPLE_TWEET]),
    ]

    report = {
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "xtf": str(XTF),
        "cases": [],
    }

    print("=== x-tweet-fetcher smoke test ===\n")
    for name, args in cases:
        print(f"→ {name}: xtf {' '.join(args)}")
        try:
            result = run_xtf(args)
        except subprocess.TimeoutExpired:
            result = {
                "cmd": [str(XTF), *args],
                "returncode": 124,
                "stdout": "",
                "stderr": "timeout",
                "json": {"error": "timeout", "error_code": "timeout"},
            }
        (OUT / f"{name}.json").write_text(
            json.dumps(result, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        summary = summarize(name, result)
        report["cases"].append(summary)
        status = "PASS" if summary["ok"] else "FAIL"
        detail = summary.get("error") or summary.get("error_code") or summary.get("text_preview") or ""
        print(f"  {status}: {detail}\n")

    report_path = OUT / "report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    passed = sum(1 for c in report["cases"] if c["ok"])
    print(f"Done: {passed}/{len(report['cases'])} passed")
    print(f"Report: {report_path}")
    return 0 if passed > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
