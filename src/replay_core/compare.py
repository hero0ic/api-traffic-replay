"""Pure response comparison.

No sockets and no clocks. The same two payloads always produce the same diffs,
which is what makes the report safe to store and safe to show a model later.
"""

import base64
import json
from typing import Any

from replay_core.models import (
    CaseResult,
    Diff,
    DiffOp,
    Exchange,
    Report,
    RequestSpec,
    Summary,
)
from replay_core.redact import redact_headers

# Latency fails when candidate exceeds max(baseline * factor, baseline + margin).
DEFAULT_LATENCY_FACTOR = 2.0
DEFAULT_LATENCY_MARGIN_MS = 100.0


def parse_ignore(patterns: list[str]) -> list[list[str]]:
    """Split dotted ignore paths. ``*`` is a single path segment, not a regex."""

    parsed: list[list[str]] = []
    for pattern in patterns:
        parts = pattern.split(".")
        if not parts or any(part == "" for part in parts):
            raise ValueError(f"invalid ignore path: {pattern!r}")
        parsed.append(parts)
    return parsed


def _ignored(path: list[str], patterns: list[list[str]]) -> bool:
    """True when a pattern matches this node or a parent of this node."""

    for pattern in patterns:
        if len(pattern) > len(path):
            continue
        if all(part == "*" or part == segment for part, segment in zip(pattern, path)):
            return True
    return False


def _shape(value: Any) -> str:
    # bool is a subclass of int, so it has to be classified first.
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, dict):
        return "dict"
    if isinstance(value, list):
        return "list"
    if isinstance(value, (int, float)):
        return "number"
    if value is None:
        return "null"
    return type(value).__name__


def _json_diff(path: list[str], op: DiffOp, baseline: Any, candidate: Any) -> Diff:
    return Diff(kind="json", path=".".join(path), op=op, baseline=baseline, candidate=candidate)


def diff_json(
    baseline: Any,
    candidate: Any,
    patterns: list[list[str]],
    prefix: list[str] | None = None,
) -> list[Diff]:
    """Deep-compare JSON values.

    Dict equality ignores key order, so identical objects return immediately.
    A volatile field still works as an ignore rule: the objects are not equal,
    the walk visits the field, and the ignore rule drops that path.
    Array indexes are significant, so ``[1, 2]`` and ``[2, 1]`` differ.
    """

    path = [] if prefix is None else prefix
    if path and _ignored(path, patterns):
        return []
    if _shape(baseline) != _shape(candidate):
        return [_json_diff(path, "replace", baseline, candidate)]
    if baseline == candidate:
        return []
    if isinstance(baseline, dict):
        return _diff_object(baseline, candidate, patterns, path)
    if isinstance(baseline, list):
        return _diff_array(baseline, candidate, patterns, path)
    return [_json_diff(path, "replace", baseline, candidate)]


def _diff_object(
    baseline: dict[Any, Any],
    candidate: dict[Any, Any],
    patterns: list[list[str]],
    prefix: list[str],
) -> list[Diff]:
    diffs: list[Diff] = []
    for key in sorted(set(baseline) | set(candidate), key=str):
        path = [*prefix, str(key)]
        if _ignored(path, patterns):
            continue
        if key not in baseline:
            diffs.append(_json_diff(path, "add", None, candidate[key]))
        elif key not in candidate:
            diffs.append(_json_diff(path, "remove", baseline[key], None))
        else:
            diffs.extend(diff_json(baseline[key], candidate[key], patterns, path))
    return diffs


def _diff_array(
    baseline: list[Any],
    candidate: list[Any],
    patterns: list[list[str]],
    prefix: list[str],
) -> list[Diff]:
    diffs: list[Diff] = []
    shared = min(len(baseline), len(candidate))
    for index in range(shared):
        diffs.extend(diff_json(baseline[index], candidate[index], patterns, [*prefix, str(index)]))
    for index in range(shared, len(baseline)):
        path = [*prefix, str(index)]
        if not _ignored(path, patterns):
            diffs.append(_json_diff(path, "remove", baseline[index], None))
    for index in range(shared, len(candidate)):
        path = [*prefix, str(index)]
        if not _ignored(path, patterns):
            diffs.append(_json_diff(path, "add", None, candidate[index]))
    return diffs


def diff_headers(
    baseline: dict[str, str],
    candidate: dict[str, str],
    *,
    extra_ignore: list[str] | None = None,
) -> list[Diff]:
    left = redact_headers(baseline, extra_ignore=extra_ignore)
    right = redact_headers(candidate, extra_ignore=extra_ignore)
    diffs: list[Diff] = []
    for name in sorted(set(left) | set(right)):
        if name not in left:
            diffs.append(Diff(kind="header", path=name, op="add", baseline=None, candidate=right[name]))
        elif name not in right:
            diffs.append(Diff(kind="header", path=name, op="remove", baseline=left[name], candidate=None))
        elif left[name] != right[name]:
            diffs.append(
                Diff(kind="header", path=name, op="replace", baseline=left[name], candidate=right[name])
            )
    return diffs


def _body_bytes(exchange: Exchange) -> bytes:
    if exchange.is_json:
        text = json.dumps(exchange.json_body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return text.encode("utf-8")
    if not exchange.body:
        return b""
    if exchange.body_encoding == "base64":
        return base64.b64decode(exchange.body)
    return exchange.body.encode("utf-8")


def _body_text(exchange: Exchange) -> str:
    if exchange.is_json:
        return json.dumps(exchange.json_body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return exchange.body or ""


def latency_threshold(
    baseline_ms: float,
    *,
    factor: float = DEFAULT_LATENCY_FACTOR,
    margin_ms: float = DEFAULT_LATENCY_MARGIN_MS,
) -> float:
    return max(baseline_ms * factor, baseline_ms + margin_ms)


def compare_responses(
    baseline: Exchange,
    candidate: Exchange,
    ignore: list[str],
    *,
    ignore_headers: list[str] | None = None,
    check_latency: bool = True,
    latency_factor: float = DEFAULT_LATENCY_FACTOR,
    latency_margin_ms: float = DEFAULT_LATENCY_MARGIN_MS,
) -> list[Diff]:
    """Compare two captured responses. The caller handles transport errors."""

    patterns = parse_ignore(ignore)
    diffs: list[Diff] = []
    if baseline.status != candidate.status:
        diffs.append(
            Diff(
                kind="status",
                path="",
                op="replace",
                baseline=baseline.status,
                candidate=candidate.status,
            )
        )
    diffs.extend(diff_headers(baseline.headers, candidate.headers, extra_ignore=ignore_headers))

    if baseline.is_json and candidate.is_json:
        diffs.extend(diff_json(baseline.json_body, candidate.json_body, patterns))
    elif baseline.is_json != candidate.is_json:
        # Mixed content types must never fall through to empty-body equality.
        diffs.append(
            Diff(
                kind="body",
                path="",
                op="replace",
                baseline=_body_text(baseline),
                candidate=_body_text(candidate),
            )
        )
    elif _body_bytes(baseline) != _body_bytes(candidate):
        diffs.append(
            Diff(
                kind="body",
                path="",
                op="replace",
                baseline=_body_text(baseline),
                candidate=_body_text(candidate),
            )
        )

    if (
        check_latency
        and baseline.elapsed_ms is not None
        and candidate.elapsed_ms is not None
    ):
        limit = latency_threshold(
            baseline.elapsed_ms,
            factor=latency_factor,
            margin_ms=latency_margin_ms,
        )
        if candidate.elapsed_ms > limit:
            diffs.append(
                Diff(
                    kind="latency",
                    path="",
                    op="replace",
                    baseline=baseline.elapsed_ms,
                    candidate=candidate.elapsed_ms,
                )
            )
    return diffs


def build_report(
    name: str,
    specs: list[RequestSpec],
    baseline: list[Exchange],
    candidate: list[Exchange],
    ignore: list[str],
    *,
    ignore_headers: list[str] | None = None,
    check_latency: bool = True,
    latency_factor: float = DEFAULT_LATENCY_FACTOR,
    latency_margin_ms: float = DEFAULT_LATENCY_MARGIN_MS,
) -> Report:
    """Match exchanges by request id and preserve the request file's order."""

    baseline_by_id = {item.id: item for item in baseline}
    candidate_by_id = {item.id: item for item in candidate}
    results = [
        _compare_one(
            spec,
            baseline_by_id.get(spec.id),
            candidate_by_id.get(spec.id),
            ignore,
            ignore_headers=ignore_headers,
            check_latency=check_latency,
            latency_factor=latency_factor,
            latency_margin_ms=latency_margin_ms,
        )
        for spec in specs
    ]
    return Report(name=name, summary=_summarize(results), results=results)


def _compare_one(
    spec: RequestSpec,
    baseline: Exchange | None,
    candidate: Exchange | None,
    ignore: list[str],
    *,
    ignore_headers: list[str] | None = None,
    check_latency: bool = True,
    latency_factor: float = DEFAULT_LATENCY_FACTOR,
    latency_margin_ms: float = DEFAULT_LATENCY_MARGIN_MS,
) -> CaseResult:
    baseline_status = None if baseline is None else baseline.status
    baseline_elapsed = None if baseline is None else baseline.elapsed_ms
    candidate_elapsed = None if candidate is None else candidate.elapsed_ms
    if candidate is None:
        return CaseResult(
            id=spec.id,
            method=spec.method,
            path=spec.path,
            outcome="errored",
            error="candidate request was not executed",
            baseline_status=baseline_status,
            baseline_elapsed_ms=baseline_elapsed,
        )
    if candidate.error:
        return CaseResult(
            id=spec.id,
            method=spec.method,
            path=spec.path,
            outcome="errored",
            error=candidate.error,
            baseline_status=baseline_status,
            candidate_status=candidate.status,
            baseline_elapsed_ms=baseline_elapsed,
            candidate_elapsed_ms=candidate_elapsed,
        )
    if baseline is None:
        return CaseResult(
            id=spec.id,
            method=spec.method,
            path=spec.path,
            outcome="errored",
            error=f"no baseline recorded for {spec.id}",
            candidate_status=candidate.status,
            candidate_elapsed_ms=candidate_elapsed,
        )
    if baseline.error:
        return CaseResult(
            id=spec.id,
            method=spec.method,
            path=spec.path,
            outcome="errored",
            error=f"baseline request failed: {baseline.error}",
            baseline_status=baseline.status,
            candidate_status=candidate.status,
            baseline_elapsed_ms=baseline_elapsed,
            candidate_elapsed_ms=candidate_elapsed,
        )
    if baseline.method != spec.method or baseline.path != spec.path:
        return CaseResult(
            id=spec.id,
            method=spec.method,
            path=spec.path,
            outcome="errored",
            error=(
                "baseline request identity mismatch: "
                f"{baseline.method} {baseline.path} vs {spec.method} {spec.path}"
            ),
            baseline_status=baseline.status,
            candidate_status=candidate.status,
            baseline_elapsed_ms=baseline_elapsed,
            candidate_elapsed_ms=candidate_elapsed,
        )
    diffs = compare_responses(
        baseline,
        candidate,
        ignore,
        ignore_headers=ignore_headers,
        check_latency=check_latency,
        latency_factor=latency_factor,
        latency_margin_ms=latency_margin_ms,
    )
    return CaseResult(
        id=spec.id,
        method=spec.method,
        path=spec.path,
        outcome="regressed" if diffs else "matched",
        diffs=diffs,
        baseline_status=baseline.status,
        candidate_status=candidate.status,
        baseline_elapsed_ms=baseline_elapsed,
        candidate_elapsed_ms=candidate_elapsed,
    )


def _summarize(results: list[CaseResult]) -> Summary:
    return Summary(
        total=len(results),
        matched=sum(result.outcome == "matched" for result in results),
        regressed=sum(result.outcome == "regressed" for result in results),
        errored=sum(result.outcome == "errored" for result in results),
    )
