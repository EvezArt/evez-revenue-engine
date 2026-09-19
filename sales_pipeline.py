#!/usr/bin/env python3
"""
EVEZ sales pipeline.

Purpose:
  Turn real commercial events into an auditable pipeline without inventing
  customers, payments, conversions, or revenue.

State machine:
  discovered -> qualified -> contacted -> replied -> proposal
  -> paid -> delivered -> recurring

The script never sends unsolicited outreach and never marks a payment as
received merely because a checkout URL exists.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(os.environ.get("EVEZ_REVENUE_HOME", Path.home() / ".evez-revenue"))
ROOT.mkdir(parents=True, exist_ok=True)
PIPELINE = ROOT / "pipeline.jsonl"
PAYMENTS = ROOT / "payments.jsonl"

STAGES = (
    "discovered",
    "qualified",
    "contacted",
    "replied",
    "proposal",
    "paid",
    "delivered",
    "recurring",
)

CATALOG = {
    "vcl-solo-artifact": {
        "name": "VCL Solo Artifact",
        "price_usd": 9.0,
        "interval": "one_time",
        "checkout": "https://buy.stripe.com/5kQ8wR6P1gF947Zf7I0RG02",
    },
    "vcl-fire-artifact": {
        "name": "VCL FIRE Artifact",
        "price_usd": 49.0,
        "interval": "one_time",
        "checkout": "https://buy.stripe.com/aFaeVf3CP74z7kb5x80RG04",
    },
    "vcl-solo-monthly": {
        "name": "VCL Solo Monthly / EVEZ OS",
        "price_usd": 49.0,
        "interval": "monthly",
        "checkout": "https://buy.stripe.com/dRmfZj4GT60v8ofbVw0RG00",
    },
    "vcl-starter": {
        "name": "VCL Starter",
        "price_usd": 299.0,
        "interval": "monthly",
        "checkout": "https://buy.stripe.com/bJe5kF4GT0Gb6g7bVw0RG01",
    },
    "evez-api-pro": {
        "name": "EVEZ API Pro",
        "price_usd": 5.0,
        "interval": "monthly",
        "checkout": "https://buy.stripe.com/00waEZflx4WrbArgbM0RG0p",
    },
    "evez-api-business": {
        "name": "EVEZ API Business",
        "price_usd": 25.0,
        "interval": "monthly",
        "checkout": "https://buy.stripe.com/00wfZj3CPex16g75x80RG0r",
    },
    "workflow-audit": {
        "name": "Workflow Audit",
        "price_usd": 250.0,
        "interval": "one_time",
        "checkout": None,
    },
}

def now() -> str:
    return datetime.now(timezone.utc).isoformat()

def append_jsonl(path: Path, event: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, sort_keys=True) + "\n")

def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows

def add_prospect(prospect_id: str, name: str = "", source: str = "") -> dict[str, Any]:
    event = {
        "event": "prospect_created",
        "prospect_id": prospect_id,
        "name": name,
        "source": source,
        "stage": "discovered",
        "ts": now(),
    }
    append_jsonl(PIPELINE, event)
    return event

def move(prospect_id: str, stage: str, note: str = "") -> dict[str, Any]:
    if stage not in STAGES:
        raise ValueError(f"Invalid stage: {stage}")
    if not any(r.get("prospect_id") == prospect_id for r in read_jsonl(PIPELINE)):
        raise ValueError(f"Unknown prospect: {prospect_id}")
    event = {
        "event": "stage_changed",
        "prospect_id": prospect_id,
        "stage": stage,
        "note": note,
        "ts": now(),
    }
    append_jsonl(PIPELINE, event)
    return event

def record_payment(
    payment_id: str,
    prospect_id: str,
    amount_usd: float,
    source_event: str,
    product: str = "",
) -> dict[str, Any]:
    if amount_usd <= 0:
        raise ValueError("Payment amount must be positive.")
    event = {
        "event": "payment_observed",
        "payment_id": payment_id,
        "prospect_id": prospect_id,
        "amount_usd": float(amount_usd),
        "product": product,
        "source_event": source_event,
        "ts": now(),
    }
    append_jsonl(PAYMENTS, event)
    return event

def status() -> dict[str, Any]:
    pipeline = read_jsonl(PIPELINE)
    payments = read_jsonl(PAYMENTS)
    latest: dict[str, str] = {}
    for row in pipeline:
        pid = row.get("prospect_id")
        if pid and row.get("event") in {"prospect_created", "stage_changed"}:
            latest[pid] = row.get("stage", "unknown")
    by_stage = {stage: 0 for stage in STAGES}
    for stage in latest.values():
        if stage in by_stage:
            by_stage[stage] += 1
    cash = sum(float(p.get("amount_usd", 0)) for p in payments)
    return {
        "prospects": len(latest),
        "by_stage": by_stage,
        "observed_cash_usd": round(cash, 2),
        "observed_payments": len(payments),
        "rule": "Only payment_observed events count as revenue.",
        "catalog_items": len(CATALOG),
    }

def offer(product: str, prospect_id: str = "") -> dict[str, Any]:
    if product not in CATALOG:
        raise ValueError(f"Unknown product: {product}")
    item = dict(CATALOG[product])
    return {
        "product_id": product,
        "prospect_id": prospect_id,
        **item,
        "generated_at": now(),
        "status": "checkout_ready" if item["checkout"] else "sales_contact_required",
    }

def main() -> int:
    p = argparse.ArgumentParser(description="EVEZ auditable sales pipeline")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("prospect-add")
    a.add_argument("prospect_id")
    a.add_argument("--name", default="")
    a.add_argument("--source", default="")

    m = sub.add_parser("move")
    m.add_argument("prospect_id")
    m.add_argument("stage", choices=STAGES)
    m.add_argument("--note", default="")

    pay = sub.add_parser("payment")
    pay.add_argument("payment_id")
    pay.add_argument("prospect_id")
    pay.add_argument("amount_usd", type=float)
    pay.add_argument("source_event")
    pay.add_argument("--product", default="")

    o = sub.add_parser("offer")
    o.add_argument("product", choices=sorted(CATALOG))
    o.add_argument("--prospect-id", default="")

    sub.add_parser("status")

    args = p.parse_args()
    try:
        if args.cmd == "prospect-add":
            result = add_prospect(args.prospect_id, args.name, args.source)
        elif args.cmd == "move":
            result = move(args.prospect_id, args.stage, args.note)
        elif args.cmd == "payment":
            result = record_payment(
                args.payment_id,
                args.prospect_id,
                args.amount_usd,
                args.source_event,
                args.product,
            )
        elif args.cmd == "offer":
            result = offer(args.product, args.prospect_id)
        else:
            result = status()
    except (ValueError, json.JSONDecodeError, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1

    print(json.dumps({"ok": True, **result}, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
