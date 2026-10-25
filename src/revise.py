"""
revise.py — component versioning with governance guardrails.

An edit produces a NEW version of a ComponentInstance (version N -> N+1). The prior
state is frozen into an append-only, hash-stamped `history` (a property list, not graph
nodes). The current node stays at its stable uid, so nothing downstream has to re-point.

Governance guardrails enforced here (an edit is rejected unless all hold):
  1. attribution    — `revised_by` is required (no anonymous edits).
  2. justification  — `change_note` is required (every change is explained).
  3. real change    — a no-op edit (content unchanged) is rejected.
  4. validity       — the edited payload must still validate against its element schema /
                      controlled vocabulary (can't edit a role to a junk value).
  5. monotonic      — version increments by exactly 1.
  6. append-only    — history grows by one frozen, hashed snapshot; prior entries untouched.
  7. provenance     — the original extraction `provenance` is carried forward unchanged;
                      revision provenance (who/why/when) is recorded separately.

`verify_history` re-checks the invariants and recomputes hashes, so tampering with a
loaded store file is detectable. Conformance runs it as a governance check.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from .models import ComponentInstance, Revision


def _canonical(payload) -> str:
    """Deterministic JSON of an element payload (model or dict), for hashing."""
    if hasattr(payload, "model_dump"):
        payload = payload.model_dump(mode="json")
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def content_hash(payload) -> str:
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def revise(instance: ComponentInstance, *, revised_by: str, change_note: str,
           **field_updates) -> ComponentInstance:
    """Return a new version of `instance` with `field_updates` applied to its payload.
    Enforces the governance guardrails above. Does not mutate the input."""
    if not (revised_by and revised_by.strip()):
        raise ValueError("revised_by is required — governance: no anonymous edits")
    if not (change_note and change_note.strip()):
        raise ValueError("change_note is required — governance: every edit must be justified")
    if not field_updates:
        raise ValueError("no field updates supplied")

    # (4) re-validate: rebuild the payload through its element model so controlled
    # vocabularies and types are enforced on the edit.
    model = type(instance.data)
    new_data = model(**{**instance.data.model_dump(), **field_updates})

    # (3) reject no-ops
    if content_hash(new_data) == content_hash(instance.data):
        raise ValueError("no-op edit: content is unchanged")

    now = datetime.now(timezone.utc)
    snapshot = Revision(
        version=instance.version,
        data=instance.data.model_dump(mode="json"),
        superseded_at=now, superseded_by=revised_by, change_note=change_note,
        hash=content_hash(instance.data),
    )
    return instance.model_copy(update={
        "data": new_data,
        "version": instance.version + 1,          # (5) monotonic +1
        "revised_at": now, "revised_by": revised_by, "change_note": change_note,
        "history": list(instance.history) + [snapshot],   # (6) append-only
        # (7) `provenance` left untouched — extraction origin preserved
    })


def verify_history(instance: ComponentInstance) -> list[str]:
    """Return a list of integrity problems (empty == clean). Detects gaps, wrong
    version numbering, hash tampering, and missing revision provenance."""
    problems = []
    n = len(instance.history)
    if n != instance.version - 1:
        problems.append(f"{instance.id}: history length {n} != version-1 ({instance.version - 1})")
    for idx, rev in enumerate(instance.history, start=1):
        if rev.version != idx:
            problems.append(f"{instance.id}: revision #{idx} has version {rev.version} (expected {idx})")
        if content_hash(rev.data) != rev.hash:
            problems.append(f"{instance.id}: revision v{rev.version} hash mismatch — history tampered")
        if not (rev.superseded_by and rev.change_note):
            problems.append(f"{instance.id}: revision v{rev.version} missing attribution/justification")
    if instance.version > 1 and not (instance.revised_by and instance.change_note):
        problems.append(f"{instance.id}: v{instance.version} lacks revision provenance (by/note)")
    return problems


def history_view(instance: ComponentInstance) -> list[dict]:
    """A readable audit trail: oldest→newest states with who/why, ending at current."""
    from .models import component_text
    rows = [{"version": r.version, "text": (r.data.get("text") or r.data.get("name") or r.data.get("description")),
             "superseded_by": r.superseded_by, "superseded_at": r.superseded_at.isoformat(),
             "change_note": r.change_note} for r in instance.history]
    rows.append({"version": instance.version, "text": component_text(instance.data),
                 "superseded_by": None, "superseded_at": None,
                 "change_note": instance.change_note, "current": True})
    return rows
