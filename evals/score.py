"""Offline extraction eval — field-level precision / recall / F1 by element type,
plus role accuracy for objectives & endpoints.

Scores the ALREADY-EXTRACTED store against a hand-labeled gold set. No API, no
Anthropic, no Neo4j — generating predictions costs money, scoring them does not.
Deliberately independent of src/ (its own text normalization) so the eval can't
flatter the code it measures.

Only gold items with "verified": true are scored. A freshly bootstrapped gold
template has verified=false on every item, so an unedited straight-through save
can't masquerade as a real gold set (it reports NOT LABELED). Human-added items
with no "verified" key default to verified.

Usage:
  python -m evals.score --study moderna_cove
  python -m evals.score --all
  python -m evals.score --study moderna_cove --md
"""
from __future__ import annotations
import argparse, glob, json, os, re
from difflib import SequenceMatcher

HERE = os.path.dirname(__file__)
STORE = os.path.join(HERE, os.pardir, "store")
GOLD = os.path.join(HERE, "gold")
REPORTS = os.path.join(HERE, "reports")
MATCH_THRESHOLD = 0.80
ROLE_TYPES = {"objective", "endpoint"}


def norm(t: str) -> str:
    t = (t or "").lower()
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _text(data: dict) -> str:
    for k in ("text", "name", "description", "label"):
        v = (data or {}).get(k)
        if v:
            return v
    return ""


def _role(inst_type: str, data: dict):
    if inst_type in ROLE_TYPES:
        return (data or {}).get("role") or (data or {}).get("level")
    return None


def load_predictions(study: str) -> list[dict]:
    d = json.load(open(os.path.join(STORE, study + ".json")))
    return [{"type": i["type"], "role": _role(i["type"], i.get("data", {})),
             "text": _text(i.get("data", {}))} for i in d["instances"]]


def load_gold(study: str) -> list[dict]:
    """Gold file: {"study_id": ..., "items": [{"type","text","role"?,"verified"?}, ...]}"""
    g = json.load(open(os.path.join(GOLD, study + ".json")))
    return g["items"]


def _by_type(items):
    out = {}
    for it in items:
        out.setdefault(it["type"], []).append(it)
    return out


def match(gold_items, pred_items, thr=MATCH_THRESHOLD):
    """Greedy best-match gold->pred by normalized similarity. Returns
    (tp, fp, fn, matched_pairs[(gold_item, pred_item, ratio)])."""
    gold_n = [norm(g["text"]) for g in gold_items]
    pred_n = [norm(p["text"]) for p in pred_items]
    used, pairs = set(), []
    for gi, gtext in enumerate(gold_n):
        best, bi = -1.0, None
        for pi, ptext in enumerate(pred_n):
            if pi in used:
                continue
            r = SequenceMatcher(None, gtext, ptext).ratio()
            if r > best:
                best, bi = r, pi
        if bi is not None and best >= thr:
            used.add(bi)
            pairs.append((gold_items[gi], pred_items[bi], round(best, 3)))
    tp = len(pairs)
    fn = len(gold_items) - tp
    fp = len(pred_items) - len(used)
    return tp, fp, fn, pairs


def _prf(tp, fp, fn):
    p = tp / (tp + fp) if (tp + fp) else 0.0
    r = tp / (tp + fn) if (tp + fn) else 0.0
    f = 2 * p * r / (p + r) if (p + r) else 0.0
    return p, r, f


def score_study(study: str, thr=MATCH_THRESHOLD) -> dict:
    gold_all, pred = load_gold(study), load_predictions(study)
    gold = [g for g in gold_all if g.get("verified", True)]
    unverified = len(gold_all) - len(gold)
    if not gold:
        return {"study": study, "threshold": thr, "rows": [], "overall": None,
                "role_accuracy": None, "role_matched": 0,
                "unverified": unverified, "gold_total": len(gold_all), "labeled": False}

    gold_t, pred_t = _by_type(gold), _by_type(pred)
    rows, tot = [], {"tp": 0, "fp": 0, "fn": 0}
    role_tp = role_ok = 0
    for t in sorted(gold_t):  # only score types the gold labels
        tp, fp, fn, pairs = match(gold_t[t], pred_t.get(t, []), thr)
        p, r, f = _prf(tp, fp, fn)
        rows.append({"type": t, "gold": len(gold_t[t]), "pred": len(pred_t.get(t, [])),
                     "tp": tp, "fp": fp, "fn": fn, "precision": p, "recall": r, "f1": f})
        tot["tp"] += tp; tot["fp"] += fp; tot["fn"] += fn
        if t in ROLE_TYPES:
            for g, pr, _ in pairs:
                role_tp += 1
                if (g.get("role") or None) == (pr.get("role") or None):
                    role_ok += 1
    mp, mr, mf = _prf(tot["tp"], tot["fp"], tot["fn"])
    return {"study": study, "threshold": thr, "rows": rows,
            "overall": {"tp": tot["tp"], "fp": tot["fp"], "fn": tot["fn"],
                        "precision": mp, "recall": mr, "f1": mf},
            "role_accuracy": (role_ok / role_tp if role_tp else None),
            "role_matched": role_tp,
            "unverified": unverified, "gold_total": len(gold_all), "labeled": True}


def format_report(s: dict) -> str:
    if not s.get("labeled", True):
        return (f"Extraction eval - {s['study']}: NOT LABELED YET\n"
                f"All {s['gold_total']} gold items are verified=false (unedited template).\n"
                f"Review evals/gold/{s['study']}.json against the protocol: set verified=true on\n"
                f"items you confirm (fix role/text, delete wrong, add missed), then re-run.")
    L = [f"Extraction eval - {s['study']}  (match >= {s['threshold']:.2f})", ""]
    if s.get("unverified"):
        L.append(f"NOTE: scoring {s['gold_total'] - s['unverified']} verified items; "
                 f"{s['unverified']} still verified=false (ignored).")
        L.append("")
    L.append(f"{'type':16} {'gold':>4} {'pred':>4} {'TP':>3} {'FP':>3} {'FN':>3} "
             f"{'P':>5} {'R':>5} {'F1':>5}")
    L.append("-" * 62)
    for r in s["rows"]:
        L.append(f"{r['type']:16} {r['gold']:>4} {r['pred']:>4} {r['tp']:>3} {r['fp']:>3} "
                 f"{r['fn']:>3} {r['precision']:>5.2f} {r['recall']:>5.2f} {r['f1']:>5.2f}")
    o = s["overall"]
    L.append("-" * 62)
    L.append(f"{'OVERALL (micro)':16} {'':>4} {'':>4} {o['tp']:>3} {o['fp']:>3} {o['fn']:>3} "
             f"{o['precision']:>5.2f} {o['recall']:>5.2f} {o['f1']:>5.2f}")
    if s["role_accuracy"] is not None:
        L.append(f"\nRole accuracy (matched obj/endpoint): "
                 f"{s['role_accuracy']:.2f}  (n={s['role_matched']})")
    return "\n".join(L)


def _main():
    ap = argparse.ArgumentParser(description="Score extraction against hand-labeled gold (offline).")
    ap.add_argument("--study")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--threshold", type=float, default=MATCH_THRESHOLD)
    ap.add_argument("--md", action="store_true", help="also write evals/reports/<study>.md")
    args = ap.parse_args()

    studies = ([os.path.basename(p)[:-5] for p in sorted(glob.glob(os.path.join(GOLD, "*.json")))
                if not p.endswith(".template.json")]
               if args.all else [args.study])
    if not studies or studies == [None]:
        ap.error("pass --study <id> or --all (and create evals/gold/<id>.json first)")
    for st in studies:
        s = score_study(st, args.threshold)
        print(format_report(s)); print()
        if args.md:
            os.makedirs(REPORTS, exist_ok=True)
            with open(os.path.join(REPORTS, st + ".md"), "w") as f:
                f.write("```\n" + format_report(s) + "\n```\n")


if __name__ == "__main__":
    _main()
