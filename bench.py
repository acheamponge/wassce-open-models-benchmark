#!/usr/bin/env python3
import argparse
import csv
import json
import os
import random
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
DEFAULT_BASE_URL = "https://api.inference.crusoecloud.com/v1"
SUBJECT_DISPLAY = {
    "core_maths": "Core Mathematics",
    "english": "English Language",
    "integrated_science": "Integrated Science",
    "social_studies": "Social Studies",
}
SKIP_PATTERN = re.compile(r"voicechat|speech|audio|embed|whisper|tts|rerank|asr", re.I)
LETTERS = ["A", "B", "C", "D"]

PROMPT_TEMPLATE = """The following is a multiple choice question from the West African Senior School Certificate Examination (WASSCE) in {subject}.

Question: {question}

A. {option_a}
B. {option_b}
C. {option_c}
D. {option_d}

Answer with just the letter of the correct option."""


def load_env():
    load_dotenv(ROOT / ".env", override=True)
    key = os.environ.get("CRUSOE_API_KEY")
    if not key:
        sys.exit("CRUSOE_API_KEY is not set. Put it in .env next to bench.py.")
    return key


def load_catalog():
    with open(ROOT / "models.json") as f:
        return json.load(f)


def subject_label(subject):
    return SUBJECT_DISPLAY.get(subject, subject.replace("_", " ").title())


def load_questions(data_dir):
    questions = []
    for path in sorted(Path(data_dir).glob("*/questions.json")):
        subject = path.parent.name
        with open(path) as f:
            for q in json.load(f):
                q = dict(q)
                q.setdefault("subject", subject)
                q.setdefault("id", f"{subject}_{len(questions) + 1:04d}")
                questions.append(q)
    return questions


def sample_questions(questions, n, seed):
    if n is None or n >= len(questions):
        return questions
    by_subject = {}
    for q in questions:
        by_subject.setdefault(q["subject"], []).append(q)
    rng = random.Random(seed)
    subjects = sorted(by_subject)
    per = max(1, n // len(subjects))
    chosen = []
    for s in subjects:
        pool = by_subject[s]
        chosen.extend(rng.sample(pool, min(per, len(pool))))
    rest = [q for q in questions if q not in chosen]
    rng.shuffle(rest)
    chosen.extend(rest[: max(0, n - len(chosen))])
    return sorted(chosen, key=lambda q: q["id"])


def build_prompt(q):
    return PROMPT_TEMPLATE.format(
        subject=subject_label(q["subject"]),
        question=q["question"].strip(),
        option_a=q["options"]["A"],
        option_b=q["options"]["B"],
        option_c=q["options"]["C"],
        option_d=q["options"]["D"],
    )


def extract_answer(text, options):
    if not text:
        return None
    cleaned = re.sub(r"[*_`#]", "", text).strip()
    if not cleaned:
        return None
    if re.fullmatch(r"\(?([A-Da-d])\)?\.?", cleaned):
        return cleaned.strip("().").upper()
    m = re.search(r"(?i)\b(?:answer|option)\s*(?:is|:)?\s*\(?([ABCD])\b", cleaned)
    if m:
        return m.group(1).upper()
    lines = [ln.strip() for ln in cleaned.splitlines() if ln.strip()]
    for ln in (lines[-1], lines[0]):
        m = re.match(r"^\(?([ABCD])\)?(?:[.:)\]]|\s|$)", ln)
        if m:
            return m.group(1).upper()
    standalone = set(re.findall(r"(?<![A-Za-z])([ABCD])(?![A-Za-z])", cleaned))
    if len(standalone) == 1:
        return standalone.pop()
    low = cleaned.lower()
    hits = [k for k, v in options.items() if v and v.strip().lower() in low]
    if len(hits) == 1:
        return hits[0]
    return None


class RateLimitError(Exception):
    def __init__(self, status, retry_after=None):
        super().__init__(f"HTTP {status}")
        self.status = status
        self.retry_after = retry_after


def call_model(session, base_url, key, model_id, prompt, temperature, max_tokens, extra, timeout):
    payload = {
        "model": model_id,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    payload.update(extra or {})
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    start = time.monotonic()
    r = session.post(f"{base_url}/chat/completions", headers=headers, json=payload, timeout=timeout)
    latency = time.monotonic() - start
    if r.status_code in (429, 500, 502, 503, 504):
        ra = r.headers.get("Retry-After")
        raise RateLimitError(r.status_code, float(ra) if ra and ra.replace(".", "", 1).isdigit() else None)
    if r.status_code != 200:
        return {"error": f"HTTP {r.status_code}: {r.text[:300]}", "latency_s": latency}
    data = r.json()
    choice = data["choices"][0]
    msg = choice.get("message", {})
    usage = data.get("usage", {}) or {}
    details = usage.get("completion_tokens_details") or {}
    return {
        "content": msg.get("content") or "",
        "reasoning": msg.get("reasoning_content") or msg.get("reasoning") or "",
        "finish_reason": choice.get("finish_reason"),
        "prompt_tokens": usage.get("prompt_tokens", 0),
        "completion_tokens": usage.get("completion_tokens", 0),
        "reasoning_tokens": details.get("reasoning_tokens", 0),
        "latency_s": latency,
    }


def call_with_retries(args, session, key, model_id, prompt, extra, log):
    delay = 1.0
    for attempt in range(args.max_retries):
        try:
            return call_model(session, args.base_url, key, model_id, prompt, args.temperature, args.max_tokens, extra, args.timeout)
        except RateLimitError as e:
            wait = e.retry_after if e.retry_after else min(60.0, delay * (1 + random.random()))
            log(f"{model_id}: HTTP {e.status}, retry {attempt + 1}/{args.max_retries} in {wait:.1f}s")
            time.sleep(wait)
            delay = min(60.0, delay * 2)
        except (requests.ConnectionError, requests.Timeout) as e:
            wait = min(60.0, delay * (1 + random.random()))
            log(f"{model_id}: {type(e).__name__}, retry {attempt + 1}/{args.max_retries} in {wait:.1f}s")
            time.sleep(wait)
            delay = min(60.0, delay * 2)
    return {"error": f"gave up after {args.max_retries} attempts", "latency_s": 0.0}


def slug(model_id):
    return model_id.replace("/", "__")


def read_done(path):
    done = {}
    if path.exists():
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    rec = json.loads(line)
                    done[rec["id"]] = rec
    return done


def run_model(args, key, model_id, info, questions, out_dir, log):
    raw_path = out_dir / "raw" / f"{slug(model_id)}.jsonl"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    done = {} if args.fresh else read_done(raw_path)
    def needs_run(rec):
        return rec.get("error") or (rec.get("predicted") is None and rec.get("finish_reason") == "length")

    todo = [q for q in questions if q["id"] not in done or needs_run(done[q["id"]])]
    if args.fresh and raw_path.exists():
        raw_path.unlink()
        done = {}
    extra = info.get("extra") or {}
    lock = threading.Lock()
    session = requests.Session()
    log(f"{model_id}: {len(todo)} questions to run, {len(done)} already done")

    def work(q):
        prompt = build_prompt(q)
        res = call_with_retries(args, session, key, model_id, prompt, extra, log)
        rec = {
            "id": q["id"],
            "subject": q["subject"],
            "topic": q.get("topic"),
            "correct_answer": q["correct_answer"],
        }
        if "error" in res:
            rec.update({"error": res["error"], "predicted": None, "is_correct": False, "latency_s": res["latency_s"]})
        else:
            pred = extract_answer(res["content"], q["options"])
            rec.update({
                "predicted": pred,
                "is_correct": pred == q["correct_answer"],
                "content": res["content"][:2000],
                "reasoning_chars": len(res["reasoning"]),
                "finish_reason": res["finish_reason"],
                "prompt_tokens": res["prompt_tokens"],
                "completion_tokens": res["completion_tokens"],
                "reasoning_tokens": res["reasoning_tokens"],
                "latency_s": round(res["latency_s"], 3),
            })
        with lock:
            done[q["id"]] = rec
            with open(raw_path, "a") as f:
                f.write(json.dumps(rec) + "\n")
        return rec

    finished = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for fut in as_completed([pool.submit(work, q) for q in todo]):
            fut.result()
            finished += 1
            if finished % 25 == 0 or finished == len(todo):
                log(f"{model_id}: {finished}/{len(todo)} done")
    if args.fresh or len(todo) < len(done):
        with open(raw_path, "w") as f:
            for q in questions:
                if q["id"] in done:
                    f.write(json.dumps(done[q["id"]]) + "\n")
    return [done[q["id"]] for q in questions if q["id"] in done]


def load_suspect_ids(data_dir):
    path = Path(data_dir) / "suspect_keys.json"
    if not path.exists():
        return set()
    with open(path) as f:
        return {item["id"] for item in json.load(f)}


def summarize_model(model_id, info, records, suspect_ids=frozenset()):
    subjects = {}
    for r in records:
        s = subjects.setdefault(r["subject"], {"correct": 0, "total": 0, "correct_reviewed": 0, "total_reviewed": 0})
        s["total"] += 1
        s["correct"] += int(bool(r.get("is_correct")))
        if r["id"] not in suspect_ids:
            s["total_reviewed"] += 1
            s["correct_reviewed"] += int(bool(r.get("is_correct")))
    for s in subjects.values():
        s["accuracy"] = round(s["correct"] / s["total"], 4) if s["total"] else 0.0
        s["accuracy_reviewed"] = round(s["correct_reviewed"] / s["total_reviewed"], 4) if s["total_reviewed"] else 0.0
    total = len(records)
    correct = sum(int(bool(r.get("is_correct"))) for r in records)
    reviewed = [r for r in records if r["id"] not in suspect_ids]
    total_reviewed = len(reviewed)
    correct_reviewed = sum(int(bool(r.get("is_correct"))) for r in reviewed)
    p_tok = sum(r.get("prompt_tokens", 0) for r in records)
    c_tok = sum(r.get("completion_tokens", 0) for r in records)
    r_tok = sum(r.get("reasoning_tokens", 0) or 0 for r in records)
    cost = None
    if info.get("input_per_m") is not None and info.get("output_per_m") is not None:
        cost = round(p_tok / 1e6 * info["input_per_m"] + c_tok / 1e6 * info["output_per_m"], 4)
    lat = [r["latency_s"] for r in records if r.get("latency_s")]
    return {
        "model": model_id,
        "name": info.get("name", model_id),
        "total": total,
        "correct": correct,
        "accuracy": round(correct / total, 4) if total else 0.0,
        "total_reviewed": total_reviewed,
        "correct_reviewed": correct_reviewed,
        "accuracy_reviewed": round(correct_reviewed / total_reviewed, 4) if total_reviewed else 0.0,
        "unparsed": sum(1 for r in records if not r.get("error") and r.get("predicted") is None),
        "errors": sum(1 for r in records if r.get("error")),
        "truncated": sum(1 for r in records if r.get("finish_reason") == "length"),
        "prompt_tokens": p_tok,
        "completion_tokens": c_tok,
        "reasoning_tokens": r_tok,
        "cost_usd": cost,
        "cost_per_1k_questions_usd": round(cost / total * 1000, 4) if cost is not None and total else None,
        "mean_latency_s": round(sum(lat) / len(lat), 3) if lat else None,
        "input_per_m": info.get("input_per_m"),
        "output_per_m": info.get("output_per_m"),
        "subjects": subjects,
    }


def write_outputs(out_dir, meta, summaries):
    subjects = sorted({s for m in summaries for s in m["subjects"]})
    summaries = sorted(summaries, key=lambda m: (-m["accuracy_reviewed"], -m["accuracy"], m["cost_usd"] if m["cost_usd"] is not None else 1e9))
    with open(out_dir / "summary.json", "w") as f:
        json.dump({"meta": meta, "models": summaries}, f, indent=2)
    with open(out_dir / "summary.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["rank", "model", "name", "accuracy_reviewed", "correct_reviewed", "total_reviewed", "accuracy", "correct", "total"]
                   + [f"acc_{s}" for s in subjects]
                   + ["unparsed", "errors", "truncated", "prompt_tokens", "completion_tokens", "reasoning_tokens",
                      "cost_usd", "cost_per_1k_questions_usd", "mean_latency_s", "input_per_m", "output_per_m"])
        for i, m in enumerate(summaries, 1):
            w.writerow([i, m["model"], m["name"], m["accuracy_reviewed"], m["correct_reviewed"], m["total_reviewed"],
                        m["accuracy"], m["correct"], m["total"]]
                       + [m["subjects"].get(s, {}).get("accuracy_reviewed", "") for s in subjects]
                       + [m["unparsed"], m["errors"], m["truncated"], m["prompt_tokens"], m["completion_tokens"],
                          m["reasoning_tokens"], m["cost_usd"], m["cost_per_1k_questions_usd"], m["mean_latency_s"],
                          m["input_per_m"], m["output_per_m"]])
    with open(out_dir / "by_subject.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["model", "name", "subject", "correct", "total", "accuracy", "correct_reviewed", "total_reviewed", "accuracy_reviewed"])
        for m in summaries:
            for s in subjects:
                d = m["subjects"].get(s)
                if d:
                    w.writerow([m["model"], m["name"], s, d["correct"], d["total"], d["accuracy"],
                                d["correct_reviewed"], d["total_reviewed"], d["accuracy_reviewed"]])
    with open(out_dir / "run_meta.json", "w") as f:
        json.dump(meta, f, indent=2)


def print_table(summaries):
    subjects = sorted({s for m in summaries for s in m["subjects"]})
    summaries = sorted(summaries, key=lambda m: (-m["accuracy_reviewed"], -m["accuracy"]))
    head = f"{'model':46s} {'reviewed':>8s} {'all':>6s} {'n':>5s} " + " ".join(f"{s[:8]:>8s}" for s in subjects) + f" {'unp':>4s} {'err':>4s} {'out_tok':>9s} {'cost$':>8s} {'lat_s':>6s}"
    print(head)
    print("-" * len(head))
    for m in summaries:
        row = f"{m['model'][:46]:46s} {m['accuracy_reviewed']:>8.1%} {m['accuracy']:>6.1%} {m['total']:>5d} "
        row += " ".join(f"{m['subjects'].get(s, {}).get('accuracy_reviewed', 0):>8.1%}" for s in subjects)
        cost = f"{m['cost_usd']:.4f}" if m["cost_usd"] is not None else "n/a"
        lat = f"{m['mean_latency_s']:.1f}" if m["mean_latency_s"] is not None else "n/a"
        row += f" {m['unparsed']:>4d} {m['errors']:>4d} {m['completion_tokens']:>9d} {cost:>8s} {lat:>6s}"
        print(row)


def list_models(base_url, key):
    r = requests.get(f"{base_url}/models", headers={"Authorization": f"Bearer {key}"}, timeout=30)
    r.raise_for_status()
    return [m["id"] for m in r.json()["data"]]


def select_models(args, key, catalog, log):
    live = list_models(args.base_url, key)
    chat = [m for m in live if not SKIP_PATTERN.search(m)]
    skipped = [m for m in live if SKIP_PATTERN.search(m) or catalog.get(m, {}).get("skip")]
    chat = [m for m in chat if not catalog.get(m, {}).get("skip")]
    if args.models:
        wanted = [m.strip() for m in args.models.split(",") if m.strip()]
        missing = [m for m in wanted if m not in live]
        if missing:
            log(f"warning: not on the live model list: {', '.join(missing)}")
        chat = wanted
    for m in chat:
        if m not in catalog:
            log(f"warning: {m} is not in models.json, cost will be unknown")
    for m in catalog:
        if m not in live and not catalog[m].get("skip"):
            log(f"note: {m} is in models.json but not served right now")
    return chat, skipped, live


def main():
    ap = argparse.ArgumentParser(description="Run Crusoe Managed Inference models on the WASSCE question bank.")
    ap.add_argument("--list-models", action="store_true")
    ap.add_argument("--models", help="comma separated model ids, default: every chat model on the live list")
    ap.add_argument("--data-dir", default=str(ROOT / "data"))
    ap.add_argument("--out", default=str(ROOT / "results"))
    ap.add_argument("--sample", type=int, help="run only this many questions, spread across subjects")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--max-tokens", type=int, default=16384)
    ap.add_argument("--workers", type=int, default=4, help="concurrent requests per model")
    ap.add_argument("--model-parallel", type=int, default=3, help="models run at the same time")
    ap.add_argument("--max-retries", type=int, default=8)
    ap.add_argument("--timeout", type=float, default=180.0)
    ap.add_argument("--base-url", default=os.environ.get("CRUSOE_BASE_URL", DEFAULT_BASE_URL))
    ap.add_argument("--fresh", action="store_true", help="ignore previous raw results")
    args = ap.parse_args()

    key = load_env()
    catalog = load_catalog()
    log_lock = threading.Lock()

    def log(msg):
        with log_lock:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

    models, skipped, live = select_models(args, key, catalog, log)
    if args.list_models:
        print("chat models to benchmark:")
        for m in models:
            print(f"  {m}  ({catalog.get(m, {}).get('name', 'not in models.json')})")
        print("skipped (not chat):")
        for m in skipped:
            print(f"  {m}")
        return

    questions = sample_questions(load_questions(args.data_dir), args.sample, args.seed)
    if not questions:
        sys.exit(f"no questions found under {args.data_dir}")
    counts = {}
    for q in questions:
        counts[q["subject"]] = counts.get(q["subject"], 0) + 1
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "run_date": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "base_url": args.base_url,
        "temperature": args.temperature,
        "max_tokens": args.max_tokens,
        "seed": args.seed,
        "sample": args.sample,
        "question_count": len(questions),
        "questions_per_subject": counts,
        "prompt_template": PROMPT_TEMPLATE,
        "models": models,
        "skipped_models": skipped,
        "live_models": live,
        "model_extra_params": {m: catalog.get(m, {}).get("extra", {}) for m in models},
    }
    log(f"{len(questions)} questions across {len(counts)} subjects, {len(models)} models, output {out_dir}")

    suspect_ids = load_suspect_ids(args.data_dir)
    meta["suspect_key_ids"] = sorted(suspect_ids)
    summaries = []
    with ThreadPoolExecutor(max_workers=max(1, args.model_parallel)) as pool:
        futs = {pool.submit(run_model, args, key, m, catalog.get(m, {}), questions, out_dir, log): m for m in models}
        for fut in as_completed(futs):
            m = futs[fut]
            records = fut.result()
            s = summarize_model(m, catalog.get(m, {}), records, suspect_ids)
            summaries.append(s)
            log(f"{m}: {s['accuracy_reviewed']:.1%} reviewed ({s['correct_reviewed']}/{s['total_reviewed']}), {s['accuracy']:.1%} all, cost ${s['cost_usd']}")
    write_outputs(out_dir, meta, summaries)
    print()
    print_table(summaries)
    print(f"\nwrote {out_dir / 'summary.json'}, summary.csv, by_subject.csv, run_meta.json")


if __name__ == "__main__":
    main()
