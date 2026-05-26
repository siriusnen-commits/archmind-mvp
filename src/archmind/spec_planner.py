from __future__ import annotations

import re
from typing import Any


def _has_word(text: str, word: str) -> bool:
    return bool(re.search(rf"\b{re.escape(str(word or '').strip().lower())}\b", str(text or "").strip().lower()))


def _field(name: str, field_type: str = "string") -> dict[str, str]:
    return {"name": name, "type": field_type}


DOMAIN_MODEL_PLANS: list[dict[str, Any]] = [
    {
        "type": "support_ticket",
        "signals": ("support ticket", "ticket manager", "support desk", "help desk", "helpdesk"),
        "entities": [
            {"name": "Ticket", "fields": [_field("title"), _field("description"), _field("status"), _field("priority"), _field("customer_id", "int"), _field("agent_id", "int")]},
            {"name": "Customer", "fields": [_field("name"), _field("email")]},
            {"name": "Agent", "fields": [_field("name"), _field("email")]},
        ],
        "relationships": [
            {"source_entity": "Ticket", "target_entity": "Customer", "field": "customer_id", "type": "belongs_to"},
            {"source_entity": "Ticket", "target_entity": "Agent", "field": "agent_id", "type": "belongs_to"},
        ],
    },
    {
        "type": "inventory_management",
        "signals": ("inventory management", "inventory manager", "stock management", "warehouse inventory"),
        "entities": [
            {"name": "Item", "fields": [_field("name"), _field("quantity", "int"), _field("category_id", "int"), _field("supplier_id", "int")]},
            {"name": "Category", "fields": [_field("name")]},
            {"name": "Supplier", "fields": [_field("name"), _field("email")]},
        ],
        "relationships": [
            {"source_entity": "Item", "target_entity": "Category", "field": "category_id", "type": "belongs_to"},
            {"source_entity": "Item", "target_entity": "Supplier", "field": "supplier_id", "type": "belongs_to"},
        ],
    },
    {
        "type": "project_management",
        "signals": ("project management", "project manager", "project tracker", "project planning"),
        "entities": [
            {"name": "Project", "fields": [_field("name"), _field("description")]},
            {"name": "Task", "fields": [_field("title"), _field("status"), _field("project_id", "int"), _field("member_id", "int")]},
            {"name": "Member", "fields": [_field("name"), _field("email")]},
        ],
        "relationships": [
            {"source_entity": "Task", "target_entity": "Project", "field": "project_id", "type": "belongs_to"},
            {"source_entity": "Task", "target_entity": "Member", "field": "member_id", "type": "belongs_to"},
        ],
    },
]


def infer_domain_model(idea: str | None, reasoning: dict[str, Any] | None = None) -> dict[str, Any]:
    text = str(idea or "").strip().lower()
    domains = {
        str(item).strip().lower()
        for item in ((reasoning or {}).get("domains") if isinstance(reasoning, dict) else []) or []
        if str(item).strip()
    }
    if not text and not domains:
        return {"entities": [], "relationships": []}

    for plan in DOMAIN_MODEL_PLANS:
        signals = tuple(str(item).strip().lower() for item in plan.get("signals", ()) if str(item).strip())
        if any(signal in text or _has_word(text, signal) for signal in signals):
            return {
                "entities": [dict(entity) for entity in plan.get("entities", []) if isinstance(entity, dict)],
                "relationships": [
                    {
                        "source_entity": str(rel.get("source_entity") or "").strip(),
                        "target_entity": str(rel.get("target_entity") or "").strip(),
                        "field": str(rel.get("field") or "").strip(),
                        "type": str(rel.get("type") or "belongs_to").strip() or "belongs_to",
                        "cardinality": "many_to_one",
                        "reason": f"{plan.get('type')} domain model",
                    }
                    for rel in plan.get("relationships", [])
                    if isinstance(rel, dict)
                ],
            }

    return {"entities": [], "relationships": []}
