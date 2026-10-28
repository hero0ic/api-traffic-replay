"""Read and write the JSON files the CLI keeps on disk."""

import json
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from replay_core.models import Baseline, Report, RequestCollection

T = TypeVar("T", bound=BaseModel)


class LoadError(Exception):
    """A request or baseline file could not be read as the expected schema."""


def load_requests(path: Path) -> RequestCollection:
    return _load(path, RequestCollection)


def load_baseline(path: Path) -> Baseline:
    return _load(path, Baseline)


def load_report(path: Path) -> Report:
    return _load(path, Report)


def save_requests(path: Path, collection: RequestCollection) -> None:
    _write(path, collection)


def save_baseline(path: Path, baseline: Baseline) -> None:
    _write(path, baseline)


def save_report(path: Path, report: Report) -> None:
    _write(path, report)


def serialize(model: BaseModel) -> str:
    payload = model.model_dump(mode="json", by_alias=True)
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def _load(path: Path, model: type[T]) -> T:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise LoadError(str(exc)) from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LoadError(f"{path}: invalid JSON on line {exc.lineno}") from exc
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        details = "; ".join(
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors()
        )
        raise LoadError(f"{path}: {details}") from exc


def _write(path: Path, model: BaseModel) -> None:
    if path.parent != Path("."):
        path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(serialize(model), encoding="utf-8")
    temporary.replace(path)
