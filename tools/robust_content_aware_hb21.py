#!/usr/bin/env python3
"""H-B2.1: out-of-source risk prediction on frozen H-B1.9 position outcomes.

Observational diagnostic only: no embedding, no proposed new codec.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from PIL import Image
from tools.robust_content_aware_hb16 import cover_features
from tools.robust_pilot_sweep import reference_image

FEATURES = ("cover_std", "cover_mean", "cover_headroom",
            "cover_edge", "cover_flat", "texture_eligible")
SCALES = (.95, .90, .85, .80, .75, .70, .65, .60)
STRATEGIES = ("random", "texture", "balanced")


def read_rows(path):
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def auc(y, score):
    """Mann-Whitney AUC, average ranks for ties; None for one-class groups."""
    y = np.asarray(y, dtype=bool)
    score = np.asarray(score, dtype=float)
    n1, n0 = int(y.sum()), int((~y).sum())
    if not n1 or not n0:
        return None
    order = np.argsort(score, kind="stable")
    values = score[order]
    ranks = np.empty(len(score), dtype=float)
    start = 0
    while start < len(score):
        end = start + 1
        while end < len(score) and values[end] == values[start]:
            end += 1
        ranks[order[start:end]] = (start + 1 + end) / 2
        start = end
    return float((ranks[y].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def fit_ridge(train_x, train_y, penalty=100.):
    """Standardized ridge least-squares risk score, not calibrated probability."""
    mu = train_x.mean(axis=0)
    sd = train_x.std(axis=0)
    sd[sd < 1e-9] = 1.
    x = (train_x - mu) / sd
    design = np.column_stack([np.ones(len(x)), x])
    regularizer = np.diag([0.] + [penalty] * train_x.shape[1])
    weights = np.linalg.solve(design.T @ design + regularizer,
                              design.T @ train_y.astype(float))
    return mu, sd, weights


def score_ridge(model, x):
    mu, sd, weights = model
    return weights[0] + ((x - mu) / sd) @ weights[1:]


def top_fraction(y, scores, fraction=.20):
    """Error fraction among the lowest-risk fifth of scored positions."""
    count = max(1, int(len(y) * fraction))
    order = np.argsort(scores, kind="stable")
    return float(np.asarray(y)[order[:count]].mean()), count


def write_csv(path, rows):
    if not rows:
        raise ValueError("No output rows")
    with path.open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def analyze(sources, positions_csv):
    source_lookup = {p.name: p for p in sources}
    features_by_source = {}
    for path in sources:
        with Image.open(path) as opened:
            ref = reference_image(opened)
        features_by_source[path.name] = cover_features(ref)
    grouped = {}
    for row in read_rows(positions_csv):
        source = row["source"]
        if source not in source_lookup:
            raise ValueError("Unknown source in CSV: " + source)
        scale = float(row["scale"])
        if scale not in SCALES:
            continue
        strategy = row["strategy"]
        if strategy not in STRATEGIES:
            raise ValueError("Unexpected strategy: " + strategy)
        index = int(row["coefficient_index"])
        values = features_by_source[source]
        if not 0 <= index < len(values["cover_std"]):
            raise ValueError("Out-of-range coefficient index")
        if int(row["wrong"]) not in (0, 1):
            raise ValueError("Invalid outcome")
        x = [float(values[f][index]) for f in FEATURES]
        grouped.setdefault((source, strategy, scale), []).append(
            (index, int(row["wrong"]), x))
    # Validate paired maps and no duplicate positions before fitting.
    for (source, strategy, scale), records in grouped.items():
        indices = [r[0] for r in records]
        if len(set(indices)) != len(indices):
            raise ValueError("Duplicate coefficient in group")
        if len(records) < 100:
            raise ValueError("Too few positions")
    summaries, predictions = [], []
    for strategy in STRATEGIES:
        for scale in SCALES:
            available = [source for source in source_lookup
                         if (source, strategy, scale) in grouped]
            if len(available) < 2:
                raise ValueError("Need at least two distinct source images")
            for heldout in available:
                train = [r for src in available if src != heldout
                         for r in grouped[(src, strategy, scale)]]
                test = grouped[(heldout, strategy, scale)]
                tx = np.asarray([r[2] for r in train], dtype=float)
                ty = np.asarray([r[1] for r in train], dtype=int)
                vx = np.asarray([r[2] for r in test], dtype=float)
                vy = np.asarray([r[1] for r in test], dtype=int)
                model = fit_ridge(tx, ty)
                scores = score_ridge(model, vx)
                selected_error, selected_n = top_fraction(vy, scores)
                # Constant score is a meaningful negative control.
                baseline = float(vy.mean())
                result = {
                    "strategy": strategy, "scale": scale,
                    "train_sources": ";".join(s for s in available if s != heldout),
                    "test_source": heldout, "n_train": len(train), "n_test": len(test),
                    "train_error_fraction": round(float(ty.mean()), 6),
                    "test_error_fraction": round(baseline, 6),
                    "auc": None if auc(vy, scores) is None else round(auc(vy, scores), 6),
                    "lowest_risk_20pct_n": selected_n,
                    "lowest_risk_20pct_error_fraction": round(selected_error, 6),
                    "risk_reduction_fraction": round(baseline - selected_error, 6),
                    "interpretation": "out-of-source observational ranking, no reembedding",
                }
                summaries.append(result)
                for (index, wrong, values), score in zip(test, scores):
                    predictions.append({
                        "strategy": strategy, "scale": scale, "test_source": heldout,
                        "coefficient_index": index, "wrong": wrong,
                        "risk_score": round(float(score), 8),
                        **dict(zip(FEATURES, values)),
                    })
                print(heldout, strategy, scale, "AUC", result["auc"],
                      "base", result["test_error_fraction"],
                      "low20", result["lowest_risk_20pct_error_fraction"], flush=True)
    return summaries, predictions


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("sources", nargs="+", type=Path)
    p.add_argument("--hb19-positions", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    args = p.parse_args()
    if args.out.exists():
        p.error("Output directory exists; refusing to overwrite")
    if len({s.name for s in args.sources}) != len(args.sources) or len(args.sources) < 2:
        p.error("Provide at least two uniquely named source images")
    if any(not s.is_file() for s in args.sources) or not args.hb19_positions.is_file():
        p.error("Missing input")
    summaries, predictions = analyze(args.sources, args.hb19_positions)
    args.out.mkdir(parents=True, exist_ok=False)
    write_csv(args.out / "heldout_summary.csv", summaries)
    write_csv(args.out / "heldout_predictions.csv", predictions)
    (args.out / "settings.json").write_text(json.dumps({
        "sources": [str(s) for s in args.sources],
        "source_sha256": {s.name: hashlib.sha256(s.read_bytes()).hexdigest()
                          for s in args.sources},
        "hb19_positions": str(args.hb19_positions),
        "hb19_positions_sha256": hashlib.sha256(args.hb19_positions.read_bytes()).hexdigest(),
        "features": list(FEATURES), "scales": list(SCALES),
        "fit": "per-strategy, per-scale standardized ridge linear probability score",
        "penalty": 100., "validation": "leave-one-image-out",
        "warning": "No actual embedding or heldout decode; low20 is hypothetical subset",
    }, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
