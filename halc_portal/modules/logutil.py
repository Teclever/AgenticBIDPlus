"""Terminal logging helpers for HAL (corporate tenders) pipeline stages."""

from __future__ import annotations

import datetime as dt
import sys


def _ts() -> str:
    return dt.datetime.now().strftime("%H:%M:%S")


def log_banner(command: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  HAL Corporate Tenders Automation — {command}")
    print(f"  Started {_ts()}")
    print(f"{'=' * 60}\n", flush=True)


def log_phase(phase_num: int, title: str) -> None:
    print(f"\n--- Phase {phase_num}: {title} ---", flush=True)


def log_info(msg: str) -> None:
    print(f"  [{_ts()}] {msg}", flush=True)


def log_step(msg: str) -> None:
    print(f"    {msg}", flush=True)


def log_warn(msg: str) -> None:
    print(f"  [{_ts()}] [warn] {msg}", flush=True)


def log_ok(msg: str) -> None:
    print(f"  [{_ts()}] {msg}", flush=True)


def log_done(summary: str = "") -> None:
    print(f"\n{'=' * 60}")
    print(f"  Finished {_ts()}")
    if summary:
        print(f"  {summary}")
    print(f"{'=' * 60}\n", flush=True)


def log_progress(current: int, total: int, label: str = "") -> None:
  if total <= 0:
      return
  suffix = f" — {label}" if label else ""
  print(f"    progress {current}/{total}{suffix}", flush=True)
