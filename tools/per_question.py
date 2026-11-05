#!/usr/bin/env python3
import argparse
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=str(ROOT / "results"))
    args = ap.parse_args()
    results = Path(args.results)
    summary = json.load(open(results / "summary.json"))
    models = summary["models"]
    names = {m["model"]: m["name"] for m in models}
    questions = {}
    for path in sorted((ROOT / "data").glob("*/questions.json")):
        for q in json.load(open(path)):
            questions[q["id"]] = q
    answers = {}
    for path in sorted((results / "raw").glob("*.jsonl")):
        model = path.stem.replace("__", "/")
        for line in open(path):
            rec = json.loads(line)
            answers.setdefault(rec["id"], {})[model] = rec
    order = [m["model"] for m in models]
    rows = []
    for qid in sorted(questions):
        q = questions[qid]
        per = answers.get(qid, {})
        missed = [names.get(m, m) for m in order if m in per and not per[m].get("is_correct")]
        rows.append((q, per, missed))
    with open(results / "per_question.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "subject", "question", "A", "B", "C", "D", "correct", "models_correct", "models_total"] + [names.get(m, m) for m in order])
        for q, per, missed in rows:
            w.writerow([q["id"], q["subject"], q["question"], q["options"]["A"], q["options"]["B"], q["options"]["C"], q["options"]["D"],
                        q["correct_answer"], len(per) - len(missed), len(per)] + [per.get(m, {}).get("predicted") or "" for m in order])
    with open(results / "per_question.md", "w") as f:
        f.write("# Questions, answer keys and model answers\n\n")
        f.write("Each entry lists the question, the key, how many models got it right, and which models missed it with the letter they gave.\n\n")
        current = None
        for q, per, missed in rows:
            if q["subject"] != current:
                current = q["subject"]
                f.write(f"## {current.replace('_', ' ').title()}\n\n")
            f.write(f"**{q['id']}** ({q.get('year', '')}) {q['question']}\n\n")
            for k in "ABCD":
                mark = " (key)" if k == q["correct_answer"] else ""
                f.write(f"- {k}. {q['options'][k]}{mark}\n")
            f.write(f"\nCorrect: {len(per) - len(missed)}/{len(per)} models.")
            if missed:
                detail = ", ".join(f"{names.get(m, m)} ({per[m].get('predicted') or 'no answer'})" for m in order if m in per and not per[m].get("is_correct"))
                f.write(f" Missed by: {detail}.")
            f.write("\n\n")
    print(f"wrote {results / 'per_question.md'} and per_question.csv")
    hard = sorted(rows, key=lambda r: -len(r[2]))[:10]
    for q, per, missed in hard:
        if missed:
            print(f"{q['id']}: {len(missed)}/{len(per)} missed, key {q['correct_answer']}: {q['question'][:80]}")


if __name__ == "__main__":
    main()
