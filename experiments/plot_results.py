"""Plot init-agent benchmark CSV results.

This script intentionally keeps plotting outside the core package. Install
matplotlib only when you want charts:

    python3 -m pip install matplotlib
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Any


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    rows = read_rows(args.csv)
    if not rows:
        print(f"No rows found in {args.csv}", file=sys.stderr)
        return 1
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print(
            "matplotlib is required to generate benchmark charts. "
            "Install it with: python3 -m pip install matplotlib",
            file=sys.stderr,
        )
        return 1

    args.output_dir.mkdir(parents=True, exist_ok=True)
    plot_hit_rates(rows, args.output_dir / "hit_rates.png", plt)
    plot_bar(rows, "noise_hit_count", "Noise Hits Per Case", "Noise hits", args.output_dir / "noise_hits.png", plt)
    plot_bar(rows, "elapsed_seconds", "Elapsed Seconds Per Case", "Seconds", args.output_dir / "elapsed_seconds.png", plt)
    plot_bar(
        rows,
        "manual_scan_reduction_percent",
        "Manual Scan Reduction Percent Per Case",
        "Reduction percent",
        args.output_dir / "manual_scan_reduction.png",
        plt,
    )
    print(f"Wrote charts to {args.output_dir}")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate simple charts from experiments/evaluate.py CSV output.")
    parser.add_argument("csv", type=Path, help="Path to results.csv produced by experiments/evaluate.py.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("experiments/results/charts"),
        help="Directory where PNG charts will be written.",
    )
    return parser.parse_args(argv)


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def plot_hit_rates(rows: list[dict[str, str]], path: Path, plt: Any) -> None:
    total = len(rows)
    rates = []
    labels = ["Top-1", "Top-3", "Top-5"]
    for key in ["top1_hit", "top3_hit", "top5_hit"]:
        hits = sum(1 for row in rows if row.get(key) == "true")
        rates.append((hits / total) * 100 if total else 0)
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.bar(labels, rates, color=["#4c78a8", "#59a14f", "#f28e2b"])
    ax.set_ylim(0, 100)
    ax.set_ylabel("Hit rate (%)")
    ax.set_title("Top-K Hit Rate")
    for index, value in enumerate(rates):
        ax.text(index, value + 1, f"{value:.1f}%", ha="center", va="bottom")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def plot_bar(rows: list[dict[str, str]], key: str, title: str, ylabel: str, path: Path, plt: Any) -> None:
    labels = [row.get("name", "") for row in rows]
    values = [_float(row.get(key)) for row in rows]
    width = max(8, min(18, len(labels) * 0.7))
    fig, ax = plt.subplots(figsize=(width, 4.8))
    ax.bar(range(len(labels)), values, color="#4c78a8")
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=45, ha="right")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def _float(value: str | None) -> float:
    if value in (None, ""):
        return 0.0
    try:
        return float(value)
    except ValueError:
        return 0.0


if __name__ == "__main__":
    raise SystemExit(main())
