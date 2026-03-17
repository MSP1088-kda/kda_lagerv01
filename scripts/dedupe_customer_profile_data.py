from __future__ import annotations

import argparse
import json
import os
import sys


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.db import get_sessionmaker  # noqa: E402
from app.services.customer_cleanup_service import dedupe_all_party_addresses  # noqa: E402


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="CRM-Adressen bereinigen und optional normalisieren.")
    parser.add_argument("--normalize-addresses", action="store_true", help="Adressschreibweisen, PLZ und Ort online pruefen und bestaetigte Werte uebernehmen.")
    parser.add_argument("--party-limit", type=int, default=0, help="Nur die ersten N Parteien verarbeiten (0 = alle).")
    parser.add_argument("--delay-ms", type=int, default=0, help="Wartezeit zwischen Online-Adresspruefungen in Millisekunden.")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    session = get_sessionmaker()()
    try:
        summary = dedupe_all_party_addresses(
            session,
            normalize=bool(args.normalize_addresses),
            party_limit=int(args.party_limit or 0),
            delay_seconds=max(0.0, float(args.delay_ms or 0) / 1000.0),
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
