#!/usr/bin/env python3
import argparse
import difflib
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
URL = "https://datasets-server.huggingface.co/rows?dataset=worldboss/waec-integrated-science-2007&config=default&split=train&offset=0&length=100"
OUT = ROOT / "data" / "integrated_science" / "questions.json"


def parse(row):
    text = row["Question"].replace("\r", "")
    m = re.search(r"\s+A\.\s", text)
    if not m:
        return None
    stem = re.sub(r"\s+", " ", text[: m.start()]).strip()
    rest = text[m.start():]
    parts = re.split(r"\s*(?:^|\n|\s{2,})([A-D])\.\s*", rest.strip())
    opts = {}
    for i in range(1, len(parts) - 1, 2):
        opts[parts[i]] = re.sub(r"\s+", " ", parts[i + 1]).strip().rstrip(",")
    if set(opts) != {"A", "B", "C", "D"}:
        return None
    answer = re.sub(r"\s+", " ", row["Answer"]).strip().rstrip(",").lower()
    letter = next((k for k, v in opts.items() if v.lower() == answer), None)
    if letter is None:
        letter = next((k for k, v in opts.items() if answer in v.lower() or v.lower() in answer), None)
    if letter is None:
        scored = sorted(((difflib.SequenceMatcher(None, answer, v.lower()).ratio(), k) for k, v in opts.items()), reverse=True)
        if scored[0][0] >= 0.85 and scored[0][0] - scored[1][0] > 0.1:
            letter = scored[0][1]
    if letter is None:
        return None
    return stem, opts, letter


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows-file", help="use a saved rows JSON instead of downloading")
    args = ap.parse_args()
    if args.rows_file:
        data = json.load(open(args.rows_file))
    else:
        with urllib.request.urlopen(URL, timeout=60) as r:
            data = json.load(r)
    existing = json.load(open(OUT)) if OUT.exists() else []
    existing = [q for q in existing if not q["id"].startswith("integrated_science_2007_")]
    added, dropped = [], []
    for i, item in enumerate(data["rows"], 1):
        parsed = parse(item["row"])
        if not parsed:
            dropped.append(item["row"]["Question"][:80])
            continue
        stem, opts, letter = parsed
        added.append({
            "id": f"integrated_science_2007_{i:03d}",
            "subject": "integrated_science",
            "year": 2007,
            "question_number": i,
            "question": stem,
            "options": opts,
            "correct_answer": letter,
            "topic": "general",
            "source": "worldboss/waec-integrated-science-2007",
        })
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(existing + added, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"wrote {len(existing) + len(added)} questions to {OUT} ({len(added)} from the 2007 set)")
    for d in dropped:
        print("dropped:", d, file=sys.stderr)


if __name__ == "__main__":
    main()
