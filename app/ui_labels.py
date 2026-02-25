from __future__ import annotations


def de_label(kind: str, value: str | None) -> str:
    if value is None:
        return ""

    mapping = {
        "track_mode": {
            "serial": "Seriennummer",
            "quantity": "Menge",
        },
        "tx_type": {
            "receipt": "Wareneingang",
            "issue": "Warenausgang",
            "transfer": "Umlagerung",
            "adjust": "Korrektur",
            "scrap": "Ausschuss",
        },
        "condition": {
            "ok": "OK/Neu",
            "used": "Gebraucht",
            "defect": "Defekt",
            "bware": "B-Ware",
        },
        "reservation_status": {
            "active": "Aktiv",
            "released": "Freigegeben",
            "fulfilled": "Erledigt",
        },
        "serial_status": {
            "in_stock": "Im Bestand",
            "reserved": "Reserviert",
            "issued": "Ausgegeben",
            "scrapped": "Verschrottet",
        },
    }

    value_str = str(value)
    return mapping.get(kind, {}).get(value_str, value_str)
