"""Build a compact LLM prompt from already-detected regressions.

The model never decides pass/fail. It only sees the regression subset of a
stored report, with truncated values and hard size limits.
"""

from __future__ import annotations

import json
from typing import Any

from replay_core.redact import REDACTION_PLACEHOLDER, is_secret_field_name, redact_json

PROMPT_VERSION = "v1"
MAX_CASES = 20
MAX_VALUE_CHARS = 200
MAX_PROMPT_BYTES = 8 * 1024

SYSTEM_PROMPT = """You explain API regressions that a deterministic replay tool already detected.
Use only the diffs in the JSON input. Do not invent changes that are not listed.
Do not claim certainty. Suggest likely breaking-change causes and what a developer should check next.
Keep the answer concise and structured with short bullet points per request id."""


class NoRegressionsError(ValueError):
    """The report has no regressed cases to explain."""


def extract_regressions(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Return compact regression cases from a stored report payload."""

    results = report.get("results") or []
    cases: list[dict[str, Any]] = []
    for result in results:
        if result.get("outcome") != "regressed":
            continue
        cases.append(
            {
                "id": result.get("id"),
                "method": result.get("method"),
                "path": result.get("path"),
                "diffs": [_compact_diff(diff) for diff in result.get("diffs") or []],
            }
        )
        if len(cases) >= MAX_CASES:
            break
    return cases


def build_diagnosis_prompt(report: dict[str, Any]) -> dict[str, Any]:
    """Build system/user messages for the chat completions API.

    Raises ``NoRegressionsError`` when there is nothing to explain.
    """

    cases = extract_regressions(report)
    if not cases:
        raise NoRegressionsError("no regressions to diagnose")

    payload: dict[str, Any] = {
        "report_name": report.get("name"),
        "summary": report.get("summary"),
        "regressions": cases,
        "truncated": False,
        "prompt_version": PROMPT_VERSION,
    }

    if len(cases) >= MAX_CASES:
        total_regressed = sum(
            1 for result in (report.get("results") or []) if result.get("outcome") == "regressed"
        )
        if total_regressed > MAX_CASES:
            payload["truncated"] = True
            payload["omitted_cases"] = total_regressed - MAX_CASES

    user_content = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if len(user_content.encode("utf-8")) > MAX_PROMPT_BYTES:
        payload["truncated"] = True
        while cases and len(user_content.encode("utf-8")) > MAX_PROMPT_BYTES:
            cases.pop()
            payload["regressions"] = cases
            payload["omitted_cases"] = payload.get("omitted_cases", 0) + 1
            user_content = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if not cases:
            raise NoRegressionsError("regressions exceeded prompt size limits")

    return {
        "prompt_version": PROMPT_VERSION,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
    }


def _compact_diff(diff: dict[str, Any]) -> dict[str, Any]:
    path = str(diff.get("path") or "")
    return {
        "kind": diff.get("kind"),
        "path": path,
        "op": diff.get("op"),
        "baseline": _truncate(_redact_diff_side(path, diff.get("baseline"))),
        "candidate": _truncate(_redact_diff_side(path, diff.get("candidate"))),
    }


def _redact_diff_side(path: str, value: Any) -> Any:
    # If the diff path itself is a secret field name, never send the raw value.
    leaf = path.rsplit(".", 1)[-1] if path else ""
    if leaf and is_secret_field_name(leaf):
        return REDACTION_PLACEHOLDER
    return redact_json(value)


def _truncate(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if len(value) <= MAX_VALUE_CHARS:
            return value
        return value[: MAX_VALUE_CHARS - 1] + "…"
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if len(text) <= MAX_VALUE_CHARS:
        return value
    return text[: MAX_VALUE_CHARS - 1] + "…"
