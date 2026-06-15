#!/usr/bin/env python3
"""Simple Codex token usage report.

Run:
    python3 token_usage_report.py

Useful options:
    python3 token_usage_report.py --since-days 7
    python3 token_usage_report.py --list-models
    python3 token_usage_report.py --model gpt-5.5

No third-party Python packages are required. The script reads ~/.codex by default.

Sources:
- sessions/**/*.jsonl and archived_sessions/**/*.jsonl: per-event token usage
  from token_count events
- state_5.sqlite: per-thread aggregate tokens_used fallback
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


# Built-in pricing presets are editable and can be tuned to your account's billing terms.
# Units are credits per 1M tokens. None means that token rate is not published
# for the model/modality in the pricing table.
MODEL_PRICING_PRESETS: dict[str, dict[str, float | None]] = {
    "chat-latest": {
        "input_cost_per_1m": 5.0,
        "cached_input_cost_per_1m": 0.5,
        "output_cost_per_1m": 30.0,
    },
    "computer-use-preview-batch": {
        "input_cost_per_1m": 1.5,
        "cached_input_cost_per_1m": None,
        "output_cost_per_1m": 6.0,
    },
    "gpt-4o-mini-transcribe": {
        "input_cost_per_1m": 1.25,
        "cached_input_cost_per_1m": None,
        "output_cost_per_1m": 5.0,
    },
    "gpt-4o-transcribe": {
        "input_cost_per_1m": 2.5,
        "cached_input_cost_per_1m": None,
        "output_cost_per_1m": 10.0,
    },
    "gpt-5-chat-latest": {
        "input_cost_per_1m": 5.0,
        "cached_input_cost_per_1m": 0.5,
        "output_cost_per_1m": 30.0,
    },
    "gpt-5.3-codex": {
        "input_cost_per_1m": 1.75,
        "cached_input_cost_per_1m": 0.175,
        "output_cost_per_1m": 14.0,
    },
    "gpt-5.3-codex-priority": {
        "input_cost_per_1m": 3.5,
        "cached_input_cost_per_1m": 0.35,
        "output_cost_per_1m": 28.0,
    },
    "gpt-5.4": {
        "input_cost_per_1m": 2.5,
        "cached_input_cost_per_1m": 0.25,
        "output_cost_per_1m": 15.0,
    },
    "gpt-5.4-batch": {
        "input_cost_per_1m": 1.25,
        "cached_input_cost_per_1m": 0.13,
        "output_cost_per_1m": 7.5,
    },
    "gpt-5.4-batch-long-context": {
        "input_cost_per_1m": 2.5,
        "cached_input_cost_per_1m": 0.25,
        "output_cost_per_1m": 11.25,
    },
    "gpt-5.4-flex": {
        "input_cost_per_1m": 1.25,
        "cached_input_cost_per_1m": 0.13,
        "output_cost_per_1m": 7.5,
    },
    "gpt-5.4-flex-long-context": {
        "input_cost_per_1m": 2.5,
        "cached_input_cost_per_1m": 0.25,
        "output_cost_per_1m": 11.25,
    },
    "gpt-5.4-long-context": {
        "input_cost_per_1m": 5.0,
        "cached_input_cost_per_1m": 0.5,
        "output_cost_per_1m": 22.5,
    },
    "gpt-5.4-mini": {
        "input_cost_per_1m": 0.75,
        "cached_input_cost_per_1m": 0.075,
        "output_cost_per_1m": 4.5,
    },
    "gpt-5.4-mini-batch": {
        "input_cost_per_1m": 0.375,
        "cached_input_cost_per_1m": 0.0375,
        "output_cost_per_1m": 2.25,
    },
    "gpt-5.4-mini-flex": {
        "input_cost_per_1m": 0.375,
        "cached_input_cost_per_1m": 0.0375,
        "output_cost_per_1m": 2.25,
    },
    "gpt-5.4-mini-priority": {
        "input_cost_per_1m": 1.5,
        "cached_input_cost_per_1m": 0.15,
        "output_cost_per_1m": 9.0,
    },
    "gpt-5.4-nano": {
        "input_cost_per_1m": 0.2,
        "cached_input_cost_per_1m": 0.02,
        "output_cost_per_1m": 1.25,
    },
    "gpt-5.4-nano-batch": {
        "input_cost_per_1m": 0.1,
        "cached_input_cost_per_1m": 0.01,
        "output_cost_per_1m": 0.625,
    },
    "gpt-5.4-nano-flex": {
        "input_cost_per_1m": 0.1,
        "cached_input_cost_per_1m": 0.01,
        "output_cost_per_1m": 0.625,
    },
    "gpt-5.4-priority": {
        "input_cost_per_1m": 5.0,
        "cached_input_cost_per_1m": 0.5,
        "output_cost_per_1m": 30.0,
    },
    "gpt-5.4-pro": {
        "input_cost_per_1m": 30.0,
        "cached_input_cost_per_1m": None,
        "output_cost_per_1m": 180.0,
    },
    "gpt-5.4-pro-batch": {
        "input_cost_per_1m": 15.0,
        "cached_input_cost_per_1m": None,
        "output_cost_per_1m": 90.0,
    },
    "gpt-5.4-pro-batch-long-context": {
        "input_cost_per_1m": 30.0,
        "cached_input_cost_per_1m": None,
        "output_cost_per_1m": 135.0,
    },
    "gpt-5.4-pro-flex": {
        "input_cost_per_1m": 15.0,
        "cached_input_cost_per_1m": None,
        "output_cost_per_1m": 90.0,
    },
    "gpt-5.4-pro-flex-long-context": {
        "input_cost_per_1m": 30.0,
        "cached_input_cost_per_1m": None,
        "output_cost_per_1m": 135.0,
    },
    "gpt-5.4-pro-long-context": {
        "input_cost_per_1m": 60.0,
        "cached_input_cost_per_1m": None,
        "output_cost_per_1m": 270.0,
    },
    "gpt-5.5": {
        "input_cost_per_1m": 5.0,
        "cached_input_cost_per_1m": 0.5,
        "output_cost_per_1m": 30.0,
    },
    "gpt-5.5-batch": {
        "input_cost_per_1m": 2.5,
        "cached_input_cost_per_1m": 0.25,
        "output_cost_per_1m": 15.0,
    },
    "gpt-5.5-batch-long-context": {
        "input_cost_per_1m": 5.0,
        "cached_input_cost_per_1m": 0.5,
        "output_cost_per_1m": 22.5,
    },
    "gpt-5.5-flex": {
        "input_cost_per_1m": 2.5,
        "cached_input_cost_per_1m": 0.25,
        "output_cost_per_1m": 15.0,
    },
    "gpt-5.5-flex-long-context": {
        "input_cost_per_1m": 5.0,
        "cached_input_cost_per_1m": 0.5,
        "output_cost_per_1m": 22.5,
    },
    "gpt-5.5-long-context": {
        "input_cost_per_1m": 10.0,
        "cached_input_cost_per_1m": 1.0,
        "output_cost_per_1m": 45.0,
    },
    "gpt-5.5-priority": {
        "input_cost_per_1m": 12.5,
        "cached_input_cost_per_1m": 1.25,
        "output_cost_per_1m": 75.0,
    },
    "gpt-5.5-pro": {
        "input_cost_per_1m": 30.0,
        "cached_input_cost_per_1m": None,
        "output_cost_per_1m": 180.0,
    },
    "gpt-5.5-pro-batch": {
        "input_cost_per_1m": 15.0,
        "cached_input_cost_per_1m": None,
        "output_cost_per_1m": 90.0,
    },
    "gpt-5.5-pro-long-context": {
        "input_cost_per_1m": 60.0,
        "cached_input_cost_per_1m": None,
        "output_cost_per_1m": 270.0,
    },
    "gpt-image-1-mini-image": {
        "input_cost_per_1m": 2.5,
        "cached_input_cost_per_1m": 0.25,
        "output_cost_per_1m": 8.0,
    },
    "gpt-image-1-mini-image-batch": {
        "input_cost_per_1m": 1.25,
        "cached_input_cost_per_1m": 0.13,
        "output_cost_per_1m": 4.0,
    },
    "gpt-image-1-mini-text": {
        "input_cost_per_1m": 2.0,
        "cached_input_cost_per_1m": 0.2,
        "output_cost_per_1m": None,
    },
    "gpt-image-1-mini-text-batch": {
        "input_cost_per_1m": 1.0,
        "cached_input_cost_per_1m": 0.1,
        "output_cost_per_1m": None,
    },
    "gpt-image-1.5-image": {
        "input_cost_per_1m": 8.0,
        "cached_input_cost_per_1m": 2.0,
        "output_cost_per_1m": 32.0,
    },
    "gpt-image-1.5-image-batch": {
        "input_cost_per_1m": 4.0,
        "cached_input_cost_per_1m": 1.0,
        "output_cost_per_1m": 16.0,
    },
    "gpt-image-1.5-text": {
        "input_cost_per_1m": 5.0,
        "cached_input_cost_per_1m": 1.25,
        "output_cost_per_1m": 10.0,
    },
    "gpt-image-1.5-text-batch": {
        "input_cost_per_1m": 2.5,
        "cached_input_cost_per_1m": 0.63,
        "output_cost_per_1m": 5.0,
    },
    "gpt-image-2-image": {
        "input_cost_per_1m": 8.0,
        "cached_input_cost_per_1m": 2.0,
        "output_cost_per_1m": 30.0,
    },
    "gpt-image-2-image-batch": {
        "input_cost_per_1m": 4.0,
        "cached_input_cost_per_1m": 1.0,
        "output_cost_per_1m": 15.0,
    },
    "gpt-image-2-text": {
        "input_cost_per_1m": 5.0,
        "cached_input_cost_per_1m": 1.25,
        "output_cost_per_1m": None,
    },
    "gpt-image-2-text-batch": {
        "input_cost_per_1m": 2.5,
        "cached_input_cost_per_1m": 0.625,
        "output_cost_per_1m": None,
    },
    "gpt-realtime-2-audio": {
        "input_cost_per_1m": 32.0,
        "cached_input_cost_per_1m": 0.4,
        "output_cost_per_1m": 64.0,
    },
    "gpt-realtime-2-image": {
        "input_cost_per_1m": 5.0,
        "cached_input_cost_per_1m": 0.5,
        "output_cost_per_1m": None,
    },
    "gpt-realtime-2-text": {
        "input_cost_per_1m": 4.0,
        "cached_input_cost_per_1m": 0.4,
        "output_cost_per_1m": 24.0,
    },
    "o3-deep-research-batch": {
        "input_cost_per_1m": 5.0,
        "cached_input_cost_per_1m": None,
        "output_cost_per_1m": 20.0,
    },
    "o4-mini-2025-04-16-finetuned": {
        "input_cost_per_1m": 4.0,
        "cached_input_cost_per_1m": 1.0,
        "output_cost_per_1m": 16.0,
    },
    "o4-mini-2025-04-16-finetuned-batch": {
        "input_cost_per_1m": 2.0,
        "cached_input_cost_per_1m": 0.5,
        "output_cost_per_1m": 8.0,
    },
    "o4-mini-2025-04-16-finetuned-data-sharing": {
        "input_cost_per_1m": 2.0,
        "cached_input_cost_per_1m": 0.5,
        "output_cost_per_1m": 8.0,
    },
    "o4-mini-2025-04-16-finetuned-data-sharing-batch": {
        "input_cost_per_1m": 1.0,
        "cached_input_cost_per_1m": 0.25,
        "output_cost_per_1m": 4.0,
    },
    "o4-mini-deep-research-batch": {
        "input_cost_per_1m": 1.0,
        "cached_input_cost_per_1m": None,
        "output_cost_per_1m": 4.0,
    },
}


@dataclass
class QueryUsage:
    ts: datetime | None
    session_id: str | None
    model: str | None
    query_preview: str
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    reasoning_tokens: int
    total_tokens: int


@dataclass
class CreditMeta:
    plan_type: str | None
    primary_used_percent: float | None
    secondary_used_percent: float | None
    credits: Any
    resets_at_primary: int | None
    resets_at_secondary: int | None


def parse_iso_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def extract_usage_from_jsonl(path: Path, since: datetime | None) -> tuple[list[QueryUsage], CreditMeta | None]:
    usages: list[QueryUsage] = []
    pending_query_text: str | None = None
    session_id: str | None = None
    current_model: str | None = None
    latest_credit: CreditMeta | None = None

    with path.open("r", encoding="utf-8") as f:
        for raw in f:
            raw = raw.strip()
            if not raw:
                continue
            try:
                row = json.loads(raw)
            except json.JSONDecodeError:
                continue

            row_ts = parse_iso_ts(row.get("timestamp"))
            if since and row_ts and row_ts < since:
                continue

            row_type = row.get("type")
            payload = row.get("payload") or {}

            if row_type == "session_meta":
                p = payload if isinstance(payload, dict) else {}
                session_id = p.get("id") or session_id
                continue

            if row_type == "turn_context":
                p = payload if isinstance(payload, dict) else {}
                current_model = p.get("model") or current_model
                continue

            if row_type == "event_msg" and isinstance(payload, dict):
                msg_type = payload.get("type")
                if msg_type == "user_message":
                    msg = payload.get("message") or ""
                    pending_query_text = " ".join(str(msg).split())[:120]
                    continue

                if msg_type == "token_count":
                    info = payload.get("info") or {}
                    last = info.get("last_token_usage") or {}

                    if not isinstance(last, dict) or not last:
                        continue

                    query_preview = pending_query_text or "(query text unavailable)"
                    pending_query_text = None

                    usages.append(
                        QueryUsage(
                            ts=row_ts,
                            session_id=session_id,
                            model=current_model,
                            query_preview=query_preview,
                            input_tokens=int(last.get("input_tokens") or 0),
                            cached_input_tokens=int(last.get("cached_input_tokens") or 0),
                            output_tokens=int(last.get("output_tokens") or 0),
                            reasoning_tokens=int(last.get("reasoning_output_tokens") or 0),
                            total_tokens=int(last.get("total_tokens") or 0),
                        )
                    )

                    rl = payload.get("rate_limits") or {}
                    primary = rl.get("primary") or {}
                    secondary = rl.get("secondary") or {}
                    latest_credit = CreditMeta(
                        plan_type=rl.get("plan_type"),
                        primary_used_percent=primary.get("used_percent"),
                        secondary_used_percent=secondary.get("used_percent"),
                        credits=rl.get("credits"),
                        resets_at_primary=primary.get("resets_at"),
                        resets_at_secondary=secondary.get("resets_at"),
                    )

    return usages, latest_credit


def query_thread_totals(state_db: Path) -> tuple[int, int, list[tuple[str, str, str, int]]]:
    if not state_db.exists():
        return 0, 0, []

    conn = sqlite3.connect(state_db)
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*), COALESCE(SUM(tokens_used), 0) FROM threads")
        thread_count, total_tokens = cur.fetchone()

        cur.execute(
            """
            SELECT id, title, COALESCE(model, ''), tokens_used
            FROM threads
            ORDER BY updated_at DESC
            LIMIT 20
            """
        )
        rows = cur.fetchall()
        return int(thread_count or 0), int(total_tokens or 0), rows
    finally:
        conn.close()


def fmt_epoch(epoch_s: int | None) -> str:
    if not epoch_s:
        return "n/a"
    return datetime.fromtimestamp(epoch_s, tz=timezone.utc).isoformat()


def fmt_rate(value: float | None) -> str:
    return "n/a" if value is None else f"{value:g}"


def fmt_int(value: int) -> str:
    return f"{value:,}"


def fmt_credits(value: float | None) -> str:
    return "n/a" if value is None else f"{value:,.6f}"


def discover_session_jsonl_files(root: Path) -> list[Path]:
    files: set[Path] = set()
    for dirname in ("sessions", "archived_sessions"):
        directory = root / dirname
        if directory.exists():
            files.update(directory.rglob("*.jsonl"))
    return sorted(files)


def detect_model(usages: list[QueryUsage], thread_rows: list[tuple[str, str, str, int]]) -> str | None:
    models = [u.model for u in usages if u.model]
    models.extend(row[2] for row in thread_rows if row[2])
    if not models:
        return None
    return Counter(models).most_common(1)[0][0]


def print_no_data_help(root: Path) -> None:
    print("No Codex token usage was found.")
    print(f"Checked: {root / 'sessions'}")
    print(f"Checked: {root / 'archived_sessions'}")
    print("Run Codex at least once, then run this script again.")


def estimate_credits(
    input_tokens: int,
    cached_input_tokens: int,
    output_tokens: int,
    input_cost_per_1m: float | None,
    cached_input_cost_per_1m: float | None,
    output_cost_per_1m: float | None,
) -> float | None:
    token_costs = (
        (input_tokens, input_cost_per_1m),
        (cached_input_tokens, cached_input_cost_per_1m),
        (output_tokens, output_cost_per_1m),
    )
    if any(tokens and cost_per_1m is None for tokens, cost_per_1m in token_costs):
        return None
    return sum(
        (tokens / 1_000_000.0) * (cost_per_1m or 0.0)
        for tokens, cost_per_1m in token_costs
    )


def rollup_usage(
    usages: list[QueryUsage],
    key_selector,
    input_cost_per_1m: float | None,
    cached_input_cost_per_1m: float | None,
    output_cost_per_1m: float | None,
) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}
    for u in usages:
        key = key_selector(u)
        if key not in buckets:
            buckets[key] = {
                "key": key,
                "events": 0,
                "input_tokens": 0,
                "cached_input_tokens": 0,
                "output_tokens": 0,
                "reasoning_output_tokens": 0,
                "total_tokens": 0,
            }

        b = buckets[key]
        b["events"] += 1
        b["input_tokens"] += u.input_tokens
        b["cached_input_tokens"] += u.cached_input_tokens
        b["output_tokens"] += u.output_tokens
        b["reasoning_output_tokens"] += u.reasoning_tokens
        b["total_tokens"] += u.total_tokens

    results = []
    for b in buckets.values():
        b["estimated_credits"] = estimate_credits(
            b["input_tokens"],
            b["cached_input_tokens"],
            b["output_tokens"],
            input_cost_per_1m,
            cached_input_cost_per_1m,
            output_cost_per_1m,
        )
        results.append(b)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Simple Codex token and estimated-credit report.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--root",
        default=str(Path.home() / ".codex"),
        help="Path to the .codex directory (default: ~/.codex)",
    )
    parser.add_argument(
        "--since-days",
        type=int,
        default=None,
        help="Only include events from the last N days.",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=0,
        help="Show top N query usage rows by total tokens.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON instead of text table.",
    )
    parser.add_argument(
        "--daily-top",
        type=int,
        default=7,
        help="Show up to N day buckets in text output.",
    )
    parser.add_argument(
        "--session-top",
        type=int,
        default=0,
        help="Show up to N session buckets in text output.",
    )
    parser.add_argument(
        "--input-credits-per-1m",
        dest="input_cost_per_1m",
        metavar="CREDITS",
        type=float,
        default=None,
        help="Estimated credits for 1M non-cached input tokens.",
    )
    parser.add_argument(
        "--input-cost-per-1m",
        dest="input_cost_per_1m",
        type=float,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--cached-input-credits-per-1m",
        dest="cached_input_cost_per_1m",
        metavar="CREDITS",
        type=float,
        default=None,
        help="Estimated credits for 1M cached input tokens.",
    )
    parser.add_argument(
        "--cached-input-cost-per-1m",
        dest="cached_input_cost_per_1m",
        type=float,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--output-credits-per-1m",
        dest="output_cost_per_1m",
        metavar="CREDITS",
        type=float,
        default=None,
        help="Estimated credits for 1M output tokens.",
    )
    parser.add_argument(
        "--output-cost-per-1m",
        dest="output_cost_per_1m",
        type=float,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Use a built-in pricing preset. Omit this to auto-detect from Codex logs.",
    )
    parser.add_argument(
        "--list-models",
        action="store_true",
        help="List built-in model pricing presets and exit.",
    )
    parser.add_argument(
        "--show-limits",
        action="store_true",
        help="Show the latest Codex usage-limit metadata if available.",
    )
    args = parser.parse_args()

    if args.list_models:
        print("Built-in pricing presets (credits per 1M tokens):")
        for name, rates in sorted(MODEL_PRICING_PRESETS.items()):
            print(
                f"- {name}: input={fmt_rate(rates['input_cost_per_1m'])}, "
                f"cached_input={fmt_rate(rates['cached_input_cost_per_1m'])}, "
                f"output={fmt_rate(rates['output_cost_per_1m'])}"
            )
        return

    root = Path(args.root).expanduser().resolve()
    since = None
    if args.since_days is not None:
        since = datetime.now(timezone.utc) - timedelta(days=args.since_days)

    jsonl_files = discover_session_jsonl_files(root)

    all_usages: list[QueryUsage] = []
    latest_credit: CreditMeta | None = None

    for jf in jsonl_files:
        usages, credit = extract_usage_from_jsonl(jf, since)
        all_usages.extend(usages)
        if credit:
            latest_credit = credit

    all_usages.sort(key=lambda x: x.total_tokens, reverse=True)
    selected = all_usages[: max(args.top, 0)]

    q_input = sum(u.input_tokens for u in all_usages)
    q_cached = sum(u.cached_input_tokens for u in all_usages)
    q_output = sum(u.output_tokens for u in all_usages)
    q_reason = sum(u.reasoning_tokens for u in all_usages)
    q_total = sum(u.total_tokens for u in all_usages)

    thread_count, thread_total, thread_rows = query_thread_totals(root / "state_5.sqlite")

    if not all_usages and thread_total == 0 and not args.json:
        print_no_data_help(root)
        return

    selected_model = args.model or detect_model(all_usages, thread_rows)
    model_source = None
    model_rates = None
    if selected_model:
        model_source = "manual" if args.model else "auto-detected"
        model_rates = MODEL_PRICING_PRESETS.get(selected_model)
        if model_rates is None and args.model:
            available = ", ".join(sorted(MODEL_PRICING_PRESETS.keys())) or "(none)"
            raise SystemExit(
                f"Unknown model preset '{selected_model}'. Use --list-models. Available: {available}"
            )

    input_cost_per_1m = (
        args.input_cost_per_1m
        if args.input_cost_per_1m is not None
        else (None if model_rates is None else model_rates["input_cost_per_1m"])
    )
    cached_input_cost_per_1m = (
        args.cached_input_cost_per_1m
        if args.cached_input_cost_per_1m is not None
        else (None if model_rates is None else model_rates["cached_input_cost_per_1m"])
    )
    output_cost_per_1m = (
        args.output_cost_per_1m
        if args.output_cost_per_1m is not None
        else (None if model_rates is None else model_rates["output_cost_per_1m"])
    )

    est_credit = None
    est_credit = estimate_credits(
        q_input,
        q_cached,
        q_output,
        input_cost_per_1m,
        cached_input_cost_per_1m,
        output_cost_per_1m,
    )

    daily_breakdown = rollup_usage(
        all_usages,
        lambda u: (u.ts.date().isoformat() if u.ts else "unknown"),
        input_cost_per_1m,
        cached_input_cost_per_1m,
        output_cost_per_1m,
    )
    daily_breakdown.sort(key=lambda x: x["key"], reverse=True)

    session_breakdown = rollup_usage(
        all_usages,
        lambda u: (u.session_id if u.session_id else "unknown"),
        input_cost_per_1m,
        cached_input_cost_per_1m,
        output_cost_per_1m,
    )
    session_breakdown.sort(key=lambda x: x["total_tokens"], reverse=True)

    if args.json:
        out = {
            "root": str(root),
            "since_days": args.since_days,
            "query_totals": {
                "events": len(all_usages),
                "input_tokens": q_input,
                "cached_input_tokens": q_cached,
                "output_tokens": q_output,
                "reasoning_output_tokens": q_reason,
                "total_tokens": q_total,
            },
            "estimated_credits": {
                "value": est_credit,
                "model_preset": selected_model,
                "model_source": model_source,
                "input_credits_per_1m": input_cost_per_1m,
                "cached_input_credits_per_1m": cached_input_cost_per_1m,
                "output_credits_per_1m": output_cost_per_1m,
            },
            "daily_breakdown": daily_breakdown,
            "session_breakdown": session_breakdown,
            "thread_totals": {
                "threads": thread_count,
                "tokens_used_sum": thread_total,
                "recent_threads": [
                    {
                        "id": r[0],
                        "title": r[1],
                        "model": r[2],
                        "tokens_used": r[3],
                    }
                    for r in thread_rows
                ],
            },
            "latest_rate_limit_meta": None
            if not latest_credit
            else {
                "plan_type": latest_credit.plan_type,
                "primary_used_percent": latest_credit.primary_used_percent,
                "secondary_used_percent": latest_credit.secondary_used_percent,
                "credits": latest_credit.credits,
                "primary_resets_at": latest_credit.resets_at_primary,
                "secondary_resets_at": latest_credit.resets_at_secondary,
                "primary_resets_at_iso": fmt_epoch(latest_credit.resets_at_primary),
                "secondary_resets_at_iso": fmt_epoch(latest_credit.resets_at_secondary),
            },
            "top_queries": [
                {
                    "timestamp": None if u.ts is None else u.ts.isoformat(),
                    "session_id": u.session_id,
                    "model": u.model,
                    "query_preview": u.query_preview,
                    "input_tokens": u.input_tokens,
                    "cached_input_tokens": u.cached_input_tokens,
                    "output_tokens": u.output_tokens,
                    "reasoning_output_tokens": u.reasoning_tokens,
                    "total_tokens": u.total_tokens,
                }
                for u in selected
            ],
        }
        print(json.dumps(out, indent=2))
        return

    print("Codex Token Usage Report")
    print(f"Data folder: {root}")
    print(f"Session files read: {len(jsonl_files)}")
    if selected_model:
        print(f"Model: {selected_model} ({model_source})")
    else:
        print("Model: unknown (pass --model, or check --list-models)")

    print("\nTotals")
    print(f"- Events: {fmt_int(len(all_usages))}")
    print(f"- Total tokens: {fmt_int(q_total)}")
    print(f"- Input tokens: {fmt_int(q_input)}")
    print(f"- Cached input tokens: {fmt_int(q_cached)}")
    print(f"- Output tokens: {fmt_int(q_output)}")
    print(f"- Reasoning output tokens: {fmt_int(q_reason)}")

    if est_credit is None:
        print("- Estimated credits: n/a")
        if selected_model and model_rates is None:
            print(f"  No built-in pricing preset for {selected_model}. Try --list-models or pass custom rates.")
        else:
            print("  Pass --model or custom per-1M token rates to estimate credits.")
    else:
        print(f"- Estimated credits: {fmt_credits(est_credit)}")
        print(
            f"  Rates per 1M tokens: input={fmt_rate(input_cost_per_1m)}, "
            f"cached={fmt_rate(cached_input_cost_per_1m)}, output={fmt_rate(output_cost_per_1m)}"
        )

    print(f"- Saved thread total: {fmt_int(thread_total)} tokens across {fmt_int(thread_count)} threads")

    if args.show_limits:
        if latest_credit:
            print("\nLatest usage-limit metadata:")
            print(
                f"  plan_type={latest_credit.plan_type} credits={latest_credit.credits} "
                f"primary_used_percent={latest_credit.primary_used_percent} "
                f"secondary_used_percent={latest_credit.secondary_used_percent}"
            )
            print(
                f"  primary_resets_at={fmt_epoch(latest_credit.resets_at_primary)} "
                f"secondary_resets_at={fmt_epoch(latest_credit.resets_at_secondary)}"
            )
        else:
            print("\nLatest usage-limit metadata: unavailable")

    if selected:
        print("\nTop query events by total tokens:")
        for i, u in enumerate(selected, start=1):
            ts = u.ts.isoformat() if u.ts else "n/a"
            print(
                f"{i:>2}. total={fmt_int(u.total_tokens):>10} "
                f"in={fmt_int(u.input_tokens):>10} out={fmt_int(u.output_tokens):>8} "
                f"ts={ts} query={u.query_preview}"
            )

    if daily_breakdown and args.daily_top > 0:
        print("\nDaily breakdown:")
        for d in daily_breakdown[: args.daily_top]:
            est = (
                "n/a"
                if d["estimated_credits"] is None
                else fmt_credits(d["estimated_credits"])
            )
            print(
                f"- day={d['key']} events={fmt_int(d['events'])} "
                f"total={fmt_int(d['total_tokens'])} in={fmt_int(d['input_tokens'])} "
                f"out={fmt_int(d['output_tokens'])} est_credits={est}"
            )

    if session_breakdown and args.session_top > 0:
        print("\nSession breakdown:")
        for s in session_breakdown[: args.session_top]:
            est = (
                "n/a"
                if s["estimated_credits"] is None
                else fmt_credits(s["estimated_credits"])
            )
            print(
                f"- session={s['key']} events={fmt_int(s['events'])} "
                f"total={fmt_int(s['total_tokens'])} in={fmt_int(s['input_tokens'])} "
                f"out={fmt_int(s['output_tokens'])} est_credits={est}"
            )


if __name__ == "__main__":
    main()
