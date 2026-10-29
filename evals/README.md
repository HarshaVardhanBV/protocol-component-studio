# Extraction evals (offline, no API)

Field-level **precision / recall / F1** per element type, plus **role accuracy**
for objectives & endpoints — scoring the already-extracted `store/` against a
hand-labeled gold set. Scoring costs nothing; only *generating* predictions
(the extractor) spends API credits. The scorer is deliberately independent of
`src/` (its own text normalization) so it can't flatter the code it measures.

## Workflow

```bash
# 1. draft a gold file from what the model extracted (fast: correct a draft, don't label from scratch)
python -m evals.make_gold --study moderna_cove        # -> evals/gold/moderna_cove.template.json

# 2. hand-label: open the template, then
#      - delete items the model got WRONG (hallucinated / mis-typed)
#      - ADD items the model MISSED (this is what measures recall — e.g. Pfizer eligibility/visits)
#      - fix the `role` on objectives/endpoints (primary / secondary / exploratory)
#    save it as evals/gold/moderna_cove.json  (drop the ".template")

# 3. score
python -m evals.score --study moderna_cove --md       # prints a scorecard; --md writes evals/reports/
python -m evals.score --all                            # every gold file
```

## Gold file format

```json
{ "study_id": "moderna_cove",
  "items": [
    {"type": "objective", "role": "primary", "text": "To evaluate the efficacy of ...", "verified": true},
    {"type": "eligibility", "text": "Age >= 18 years at screening"}
  ] }
```
`role` is only used for `objective` / `endpoint`. **`verified` is the honesty gate:**
`make_gold` writes every bootstrapped item as `"verified": false`; the scorer ignores
those, so an unedited template reports **NOT LABELED** instead of a fake 1.00. Set
`verified: true` only on items you've checked against the protocol. Items you add by
hand (no `verified` key) default to verified.

## How to read it — and one honest caveat

- **Recall** = of the true items you labeled, how many the model found. This is the
  headline number and it needs only the items present. Pfizer's missing
  eligibility/visits show up here as recall 0 for those types.
- **Precision** = of what the model returned, how much was right. **Precision is
  only meaningful when the gold COMPLETELY labels that element type for that
  study** — every true item present. A partial gold makes real extractions look
  like false positives and understates precision. Label a type fully, or read
  recall only for partially-labeled types.
- **Role accuracy** = among matched objectives/endpoints, the fraction with the
  correct role. This isolates the over-tagging problem (e.g. Pfizer's inflated
  "primary" counts) from recall/precision.
- Matching is fuzzy (normalized `SequenceMatcher` ratio >= 0.80) so lightly
  cleaned text still matches; tune with `--threshold`.

## Suggested labeled set

Start with the two onboarded COVID studies, then add **KEYNOTE-189 (NCT02578680)**
so oncology extraction is measured too — that closes the WS-B scalability caveat
(structure was proven indication-agnostic; this measures *accuracy* on a new area).
