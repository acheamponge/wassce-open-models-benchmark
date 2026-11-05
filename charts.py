#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

ROOT = Path(__file__).resolve().parent
BLUE = "#2a78d6"
BLUE_DARK = "#1c5cab"
SURFACE = "#fcfcfb"
TEXT = "#0b0b0b"
TEXT_2 = "#52514e"
GRID = "#e6e5e1"
SUBJECT_DISPLAY = {
    "core_maths": "Core Mathematics",
    "english": "English Language",
    "integrated_science": "Integrated Science",
    "social_studies": "Social Studies",
}


def acc(m):
    return m.get("accuracy_reviewed", m["accuracy"])


def sacc(d):
    return d.get("accuracy_reviewed", d.get("accuracy", 0))


def rank_key(m):
    cost = m.get("cost_usd")
    return (acc(m), m["accuracy"], -(cost if cost is not None else 1e9))


def style(ax):
    ax.set_facecolor(SURFACE)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=TEXT_2, length=0)
    ax.xaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def accuracy_chart(models, out):
    models = sorted(models, key=rank_key)
    names = [m["name"] for m in models]
    vals = [acc(m) * 100 for m in models]
    fig, ax = plt.subplots(figsize=(10.5, 0.5 * len(models) + 1.6), facecolor=SURFACE)
    style(ax)
    bars = ax.barh(names, vals, color=BLUE, height=0.62)
    bars[-1].set_color(BLUE_DARK)
    for b, m in zip(bars, models):
        label = f"{acc(m) * 100:.1f}%  ({m['correct']}/{m['total']} on all items)"
        ax.text(b.get_width() + 0.8, b.get_y() + b.get_height() / 2, label, va="center", color=TEXT, fontsize=9)
    ax.set_xlim(0, 145)
    ax.set_xticks([0, 20, 40, 60, 80, 100])
    ax.set_xlabel("Accuracy on reviewed WASSCE objective questions (%)", color=TEXT_2)
    n = models[0].get("total_reviewed", models[0]["total"])
    ax.set_title(f"Accuracy on Crusoe Managed Inference, {n} reviewed WASSCE questions", loc="left", color=TEXT, fontsize=13, pad=12)
    fig.tight_layout()
    fig.savefig(out, dpi=200, facecolor=SURFACE)
    plt.close(fig)


def subject_chart(models, out):
    subjects = [s for s in SUBJECT_DISPLAY if any(s in m["subjects"] for m in models)]
    subjects += sorted({s for m in models for s in m["subjects"]} - set(subjects))
    order = [m["name"] for m in sorted(models, key=rank_key)]
    cols = 2 if len(subjects) > 1 else 1
    rows = (len(subjects) + cols - 1) // cols
    fig, axes = plt.subplots(rows, cols, figsize=(6.2 * cols, (0.42 * len(models) + 1.4) * rows), facecolor=SURFACE, squeeze=False)
    for ax, s in zip(axes.flat, subjects):
        style(ax)
        vals = {m["name"]: sacc(m["subjects"].get(s, {})) * 100 for m in models}
        bars = ax.barh(order, [vals[n] for n in order], color=BLUE, height=0.62)
        for b, n in zip(bars, order):
            ax.text(b.get_width() + 1, b.get_y() + b.get_height() / 2, f"{vals[n]:.0f}", va="center", color=TEXT, fontsize=9)
        ax.set_xlim(0, 112)
        ax.set_xticks([0, 20, 40, 60, 80, 100])
        total = next((m["subjects"][s].get("total_reviewed", m["subjects"][s]["total"]) for m in models if s in m["subjects"]), 0)
        ax.set_title(f"{SUBJECT_DISPLAY.get(s, s)} ({total} questions)", loc="left", color=TEXT, fontsize=11)
        ax.tick_params(axis="y", labelsize=9)
    for ax in list(axes.flat)[len(subjects):]:
        ax.axis("off")
    fig.suptitle("Accuracy by subject (%)", x=0.01, ha="left", color=TEXT, fontsize=13)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    fig.savefig(out, dpi=200, facecolor=SURFACE)
    plt.close(fig)


def cost_chart(models, out):
    pts = [m for m in models if m.get("cost_per_1k_questions_usd")]
    if not pts:
        return
    pts = sorted(pts, key=lambda m: -m["cost_per_1k_questions_usd"])
    names = [m["name"] for m in pts]
    vals = [m["cost_per_1k_questions_usd"] for m in pts]
    fig, ax = plt.subplots(figsize=(9, 0.5 * len(pts) + 1.6), facecolor=SURFACE)
    style(ax)
    ax.set_xscale("log")
    bars = ax.barh(names, vals, color=BLUE, height=0.62)
    bars[-1].set_color(BLUE_DARK)
    for b, m in zip(bars, pts):
        ax.text(b.get_width() * 1.12, b.get_y() + b.get_height() / 2, f"${m['cost_per_1k_questions_usd']:.2f}   {acc(m) * 100:.1f}% accuracy", va="center", color=TEXT, fontsize=9)
    ax.set_xlim(min(vals) * 0.6, max(vals) * 12)
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"${v:g}"))
    ax.set_xlabel("Cost per 1,000 questions at list price, log scale", color=TEXT_2)
    ax.set_title("What the same exam costs on each model", loc="left", color=TEXT, fontsize=13, pad=12)
    fig.tight_layout()
    fig.savefig(out, dpi=200, facecolor=SURFACE)
    plt.close(fig)


def latency_chart(models, out):
    pts = [m for m in models if m.get("mean_latency_s")]
    pts = sorted(pts, key=lambda m: -m["mean_latency_s"])
    names = [m["name"] for m in pts]
    vals = [m["mean_latency_s"] for m in pts]
    fig, ax = plt.subplots(figsize=(10.5, 0.5 * len(pts) + 1.6), facecolor=SURFACE)
    style(ax)
    bars = ax.barh(names, vals, color=BLUE, height=0.62)
    bars[-1].set_color(BLUE_DARK)
    for b, m in zip(bars, pts):
        tok = m["completion_tokens"] / m["total"] if m["total"] else 0
        ax.text(b.get_width() + max(vals) * 0.015, b.get_y() + b.get_height() / 2, f"{m['mean_latency_s']:.1f} s   {tok:.0f} output tokens per question", va="center", color=TEXT, fontsize=9)
    ax.set_xlim(0, max(vals) * 1.9)
    ax.set_xlabel("Mean response time per question (seconds)", color=TEXT_2)
    ax.set_title("Response time and output length", loc="left", color=TEXT, fontsize=13, pad=12)
    fig.tight_layout()
    fig.savefig(out, dpi=200, facecolor=SURFACE)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=str(ROOT / "results"))
    ap.add_argument("--out", default=str(ROOT / "charts"))
    args = ap.parse_args()
    with open(Path(args.results) / "summary.json") as f:
        models = json.load(f)["models"]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    accuracy_chart(models, out / "accuracy_overall.png")
    subject_chart(models, out / "accuracy_by_subject.png")
    cost_chart(models, out / "cost_per_1k_questions.png")
    latency_chart(models, out / "latency.png")
    print(f"wrote charts to {out}")


if __name__ == "__main__":
    main()
