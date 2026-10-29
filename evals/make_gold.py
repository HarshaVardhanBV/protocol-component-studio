"""Bootstrap an editable gold file from the current store predictions.

Writes evals/gold/<study>.template.json pre-filled with what the model extracted,
every item flagged "verified": false. You then review each against the protocol:
flip verified=true on items you confirm (fix role/text), delete wrong ones, add
missed ones — and save as evals/gold/<study>.json. The scorer ignores anything
still verified=false, so an unedited template can't masquerade as a real gold set.
"""
from __future__ import annotations
import argparse, json, os
from .score import load_predictions, GOLD


def _main():
    ap = argparse.ArgumentParser(description="Make an editable gold template from store predictions.")
    ap.add_argument("--study", required=True)
    args = ap.parse_args()
    os.makedirs(GOLD, exist_ok=True)
    items = [{"type": p["type"], "role": p["role"], "text": p["text"], "verified": False}
             for p in load_predictions(args.study)]
    out = os.path.join(GOLD, args.study + ".template.json")
    with open(out, "w") as f:
        json.dump({"study_id": args.study, "items": items}, f, indent=2)
    print(f"wrote {out} ({len(items)} items, all verified=false) — review each, set "
          f"verified=true (fix role/text, delete wrong, add missed), save as {args.study}.json")


if __name__ == "__main__":
    _main()
