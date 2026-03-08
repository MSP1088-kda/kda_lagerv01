from __future__ import annotations

from collections import defaultdict


def _clean(value) -> str:
    return str(value or "").strip()


def _cluster_sort_key(payload: dict) -> tuple:
    return (
        0 if payload.get("anchor_system") == "outsmart" else 1,
        0 if payload.get("status") == "ready" else 1,
        -int(round(float(payload.get("confidence") or 0))),
        _clean(payload.get("display_name")).lower(),
        _clean(payload.get("cluster_key")).lower(),
    )


def build_customer_init_clusters(
    *,
    outsmart_relations: list[dict],
    outsmart_projects: list[dict],
    outsmart_workorders: list[dict],
    sevdesk_contacts: list[dict],
    sevdesk_orders: list[dict],
    sevdesk_invoices: list[dict],
    sevdesk_stats: list[dict],
) -> list[dict]:
    clusters: list[dict] = []
    by_key: dict[str, dict] = {}
    by_debtor: dict[str, dict] = {}
    by_email: dict[str, list[dict]] = defaultdict(list)
    by_phone: dict[str, list[dict]] = defaultdict(list)
    by_name_zip: dict[tuple[str, str], list[dict]] = defaultdict(list)

    def ensure_cluster(*, cluster_key: str, anchor_system: str, anchor_key: str, display_name: str) -> dict:
        row = by_key.get(cluster_key)
        if row is None:
            row = {
                "cluster_key": cluster_key,
                "anchor_system": anchor_system,
                "anchor_key": anchor_key,
                "display_name": display_name,
                "status": "ready",
                "confidence": 100.0 if anchor_system == "outsmart" else 80.0,
                "conflict_note": "",
                "members": [],
                "summary": {},
            }
            by_key[cluster_key] = row
            clusters.append(row)
        return row

    def add_member(cluster: dict, member: dict) -> None:
        cluster["members"].append(member)

    for row in outsmart_relations:
        debtor_norm = _clean(row.get("debtor_norm"))
        relation_no = _clean(row.get("relation_no"))
        anchor_key = debtor_norm or relation_no or f"row-{int(row.get('id') or 0)}"
        cluster = ensure_cluster(
            cluster_key=f"outsmart:{anchor_key}",
            anchor_system="outsmart",
            anchor_key=relation_no or anchor_key,
            display_name=_clean(row.get("name")) or relation_no or anchor_key,
        )
        add_member(
            cluster,
            {
                "source_system": "outsmart",
                "source_type": "relation_stage",
                "stage_row_id": int(row.get("id") or 0) or None,
                "external_key": relation_no or debtor_norm,
                "external_secondary_key": _clean(row.get("debtor_no")) or None,
                "display_name": _clean(row.get("name")) or relation_no or debtor_norm,
                "match_score": 100.0,
                "match_reason": "OutSmart-Anker",
                "is_anchor": True,
                "meta": {
                    "city": _clean(row.get("city")),
                    "zip_code": _clean(row.get("zip_code")),
                },
            },
        )
        if debtor_norm:
            by_debtor[debtor_norm] = cluster
        email_norm = _clean(row.get("email_norm"))
        if email_norm:
            by_email[email_norm].append(cluster)
        phone_norm = _clean(row.get("phone_norm"))
        if phone_norm:
            by_phone[phone_norm].append(cluster)
        name_zip_key = (_clean(row.get("name_norm")), _clean(row.get("zip_norm")))
        if all(name_zip_key):
            by_name_zip[name_zip_key].append(cluster)

    for row in outsmart_projects:
        debtor_norm = _clean(row.get("debtor_norm")) or _clean(row.get("customer_number_norm"))
        cluster = by_debtor.get(debtor_norm)
        if not cluster:
            continue
        add_member(
            cluster,
            {
                "source_system": "outsmart",
                "source_type": "project_stage",
                "stage_row_id": int(row.get("id") or 0) or None,
                "external_key": _clean(row.get("project_code")) or None,
                "external_secondary_key": _clean(row.get("debtor_number_invoice")) or None,
                "display_name": _clean(row.get("name")) or _clean(row.get("project_code")),
                "match_score": 100.0,
                "match_reason": "Projekt zur OutSmart-Debitornummer",
                "is_anchor": False,
                "meta": {"status": _clean(row.get("status"))},
            },
        )

    for row in outsmart_workorders:
        debtor_norm = _clean(row.get("debtor_norm")) or _clean(row.get("customer_number_norm"))
        cluster = by_debtor.get(debtor_norm)
        if not cluster:
            continue
        add_member(
            cluster,
            {
                "source_system": "outsmart",
                "source_type": "workorder_stage",
                "stage_row_id": int(row.get("id") or 0) or None,
                "external_key": _clean(row.get("workorder_no")) or None,
                "external_secondary_key": _clean(row.get("project_code")) or None,
                "display_name": _clean(row.get("customer_name")) or _clean(row.get("workorder_no")),
                "match_score": 100.0,
                "match_reason": "Arbeitsauftrag zur OutSmart-Debitornummer",
                "is_anchor": False,
                "meta": {"status": _clean(row.get("status"))},
            },
        )

    sevdesk_cluster_by_contact: dict[str, dict] = {}

    def score_candidates(contact: dict) -> tuple[dict | None, float, list[str], bool]:
        customer_number_norm = _clean(contact.get("customer_number_norm"))
        email_norm = _clean(contact.get("email_norm"))
        phone_norm = _clean(contact.get("phone_norm"))
        name_norm = _clean(contact.get("name_norm"))
        zip_norm = _clean(contact.get("zip_norm"))
        street_norm = _clean(contact.get("street_norm"))
        city_norm = _clean(contact.get("city_norm"))
        candidate_scores: dict[str, dict[str, object]] = {}

        def add_score(cluster: dict, points: float, reason: str) -> None:
            payload = candidate_scores.setdefault(cluster["cluster_key"], {"cluster": cluster, "score": 0.0, "reasons": []})
            payload["score"] = float(payload["score"]) + float(points)
            payload["reasons"].append(reason)

        if customer_number_norm and customer_number_norm in by_debtor:
            add_score(by_debtor[customer_number_norm], 120.0, "Gleiche Debitor-/Kundennummer")
        if email_norm:
            for cluster in by_email.get(email_norm, []):
                add_score(cluster, 60.0, "Gleiche E-Mail")
        if phone_norm:
            for cluster in by_phone.get(phone_norm, []):
                add_score(cluster, 40.0, "Gleiche Telefonnummer")
        if name_norm and zip_norm:
            for cluster in by_name_zip.get((name_norm, zip_norm), []):
                add_score(cluster, 35.0, "Gleicher Name + PLZ")
        if not candidate_scores:
            return None, 0.0, [], False
        ordered = sorted(candidate_scores.values(), key=lambda item: (-float(item["score"]), item["cluster"]["cluster_key"]))
        best = ordered[0]
        ambiguous = len(ordered) > 1 and float(ordered[1]["score"]) >= float(best["score"]) - 15.0
        if street_norm and city_norm and not ambiguous:
            float(best["score"])
        return best["cluster"], float(best["score"]), list(best["reasons"]), ambiguous

    sevdesk_groups: dict[str, dict] = {}
    for row in sevdesk_contacts:
        cluster, score, reasons, ambiguous = score_candidates(row)
        if cluster is None:
            anchor = _clean(row.get("customer_number_norm")) or _clean(row.get("email_norm")) or f"contact-{_clean(row.get('sevdesk_contact_id'))}"
            key = f"sevdesk:{anchor}"
            cluster = sevdesk_groups.get(key)
            if cluster is None:
                cluster = ensure_cluster(
                    cluster_key=key,
                    anchor_system="sevdesk",
                    anchor_key=_clean(row.get("sevdesk_contact_id")) or anchor,
                    display_name=_clean(row.get("name")) or _clean(row.get("customer_number")) or anchor,
                )
                cluster["confidence"] = 70.0
                sevdesk_groups[key] = cluster
            reasons = ["Nur sevDesk-Daten vorhanden"]
            score = 70.0
        elif ambiguous:
            cluster["status"] = "needs_review"
            cluster["conflict_note"] = "Mehrere mögliche OutSmart-Zuordnungen mit ähnlicher Wertung."
        elif score < 80.0:
            cluster["status"] = "needs_review"
            cluster["conflict_note"] = "Treffer ist schwach und sollte geprüft werden."
        cluster["confidence"] = max(float(cluster.get("confidence") or 0.0), score)
        contact_id = _clean(row.get("sevdesk_contact_id"))
        add_member(
            cluster,
            {
                "source_system": "sevdesk",
                "source_type": "contact_stage",
                "stage_row_id": int(row.get("id") or 0) or None,
                "external_key": contact_id or None,
                "external_secondary_key": _clean(row.get("customer_number")) or None,
                "display_name": _clean(row.get("name")) or contact_id,
                "match_score": score,
                "match_reason": ", ".join(reasons),
                "is_anchor": cluster["anchor_system"] == "sevdesk" and cluster["anchor_key"] == contact_id,
                "meta": {
                    "city": _clean(row.get("city")),
                    "zip_code": _clean(row.get("zip_code")),
                },
            },
        )
        if contact_id:
            sevdesk_cluster_by_contact[contact_id] = cluster

    for row in sevdesk_orders:
        contact_id = _clean(row.get("contact_id"))
        cluster = sevdesk_cluster_by_contact.get(contact_id)
        if not cluster:
            continue
        add_member(
            cluster,
            {
                "source_system": "sevdesk",
                "source_type": "order_stage",
                "stage_row_id": int(row.get("id") or 0) or None,
                "external_key": _clean(row.get("sevdesk_order_id")) or None,
                "external_secondary_key": _clean(row.get("order_number")) or None,
                "display_name": _clean(row.get("order_number")) or _clean(row.get("sevdesk_order_id")),
                "match_score": 100.0,
                "match_reason": "An sevDesk-Kontakt gekoppelt",
                "is_anchor": False,
                "meta": {"status": _clean(row.get("status"))},
            },
        )

    for row in sevdesk_invoices:
        contact_id = _clean(row.get("contact_id"))
        cluster = sevdesk_cluster_by_contact.get(contact_id)
        if not cluster:
            continue
        add_member(
            cluster,
            {
                "source_system": "sevdesk",
                "source_type": "invoice_stage",
                "stage_row_id": int(row.get("id") or 0) or None,
                "external_key": _clean(row.get("sevdesk_invoice_id")) or None,
                "external_secondary_key": _clean(row.get("invoice_number")) or None,
                "display_name": _clean(row.get("invoice_number")) or _clean(row.get("sevdesk_invoice_id")),
                "match_score": 100.0,
                "match_reason": "An sevDesk-Kontakt gekoppelt",
                "is_anchor": False,
                "meta": {"status": _clean(row.get("status"))},
            },
        )

    for row in sevdesk_stats:
        contact_id = _clean(row.get("sevdesk_contact_id"))
        cluster = sevdesk_cluster_by_contact.get(contact_id)
        if not cluster:
            continue
        cluster["summary"][contact_id] = {
            "orders": int(row.get("order_count") or 0),
            "invoices": int(row.get("invoice_count") or 0),
            "credit_notes": int(row.get("credit_note_count") or 0),
            "vouchers": int(row.get("voucher_count") or 0),
        }

    for cluster in clusters:
        member_types = defaultdict(int)
        for member in cluster["members"]:
            member_types[_clean(member.get("source_type"))] += 1
        summary = dict(cluster.get("summary") or {})
        summary.update(
            {
                "member_count": len(cluster["members"]),
                "relation_count": member_types.get("relation_stage", 0),
                "project_count": member_types.get("project_stage", 0),
                "workorder_count": member_types.get("workorder_stage", 0),
                "contact_count": member_types.get("contact_stage", 0),
                "order_count": member_types.get("order_stage", 0),
                "invoice_count": member_types.get("invoice_stage", 0),
            }
        )
        cluster["summary"] = summary
    return sorted(clusters, key=_cluster_sort_key)
