from __future__ import annotations


def de_label(kind: str, value: str | None) -> str:
    if value is None:
        return ""

    mapping = {
        "track_mode": {
            "serial": "Menge",
            "quantity": "Menge",
        },
        "item_type": {
            "appliance": "Großgerät",
            "spare_part": "Ersatzteil",
            "accessory": "Zubehör",
            "material": "Material",
        },
        "tx_type": {
            "receipt": "Wareneingang",
            "issue": "Warenausgang",
            "transfer": "Umlagerung",
            "adjust": "Korrektur",
            "scrap": "Ausschuss",
        },
        "condition": {
            "A_WARE": "A-Ware (Neu)",
            "B_WARE": "B-Ware (aufbereitet)",
            "GEBRAUCHT": "Gebraucht (Kundenrücknahme)",
            "NEUPUNKT": "Neupunkt",
            "IN_REPARATUR": "In Reparatur",
            # Legacy compatibility
            "ok": "A-Ware (Neu)",
            "bware": "B-Ware (aufbereitet)",
            "used": "Gebraucht (Kundenrücknahme)",
            "defect": "In Reparatur",
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
