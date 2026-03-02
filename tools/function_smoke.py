from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def _dt(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


def main() -> int:
    src_dir = Path(__file__).resolve().parents[1] / "src"
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))

    from dks import ClaimCore, KnowledgeStore, Provenance, TransactionTime, ValidTime

    store = KnowledgeStore()
    core = ClaimCore(
        claim_type="residence",
        slots={"subject": "ada lovelace"},
    )
    rev = store.assert_revision(
        core=core,
        assertion="Ada lives in London",
        valid_time=ValidTime(start=_dt(2024, 1, 1), end=None),
        transaction_time=TransactionTime(tx_id=1, recorded_at=_dt(2024, 1, 2)),
        provenance=Provenance(source="smoke_source"),
        confidence_bp=9000,
    )
    queried = store.query_as_of(
        core.core_id,
        valid_at=_dt(2024, 6, 1),
        tx_id=1,
    )

    if queried is None:
        raise RuntimeError("smoke query returned None")
    if queried.revision_id != rev.revision_id:
        raise RuntimeError("smoke query returned unexpected revision")

    payload = {
        "ok": True,
        "core_id": core.core_id,
        "revision_id": rev.revision_id,
    }
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
