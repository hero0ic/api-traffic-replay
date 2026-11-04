"""File and report types shared by the CLI, the diff engine, and later storage.

The request file is the input a developer checks in. The baseline file is
captured output. The report is the contract other tools will read.
"""

from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Outcome = Literal["matched", "regressed", "errored"]
DiffKind = Literal["status", "header", "json", "body", "latency"]
DiffOp = Literal["replace", "add", "remove"]
BodyEncoding = Literal["utf-8", "base64"]


class RequestSpec(BaseModel):
    """One HTTP call, independent of every other call in the file."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    id: str
    method: str
    path: str
    headers: dict[str, str] = Field(default_factory=dict)
    json_body: Any = Field(default=None, alias="json")
    body: str | None = None

    @field_validator("id")
    @classmethod
    def id_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("id must not be blank")
        return value

    @field_validator("method")
    @classmethod
    def normalize_method(cls, value: str) -> str:
        method = value.strip().upper()
        if not method:
            raise ValueError("method must not be blank")
        return method

    @field_validator("path")
    @classmethod
    def path_must_start_at_the_root(cls, value: str) -> str:
        if not value.startswith("/"):
            raise ValueError("path must start with /")
        return value

    @model_validator(mode="after")
    def one_body_form(self) -> Self:
        if self.json_body is not None and self.body is not None:
            raise ValueError("set json or body, not both")
        return self


class RequestCollection(BaseModel):
    """A named list of requests plus the JSON paths that are allowed to change."""

    model_config = ConfigDict(extra="forbid")

    name: str
    ignore: list[str] = Field(default_factory=list)
    ignore_headers: list[str] = Field(default_factory=list)
    requests: list[RequestSpec]

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("name must not be blank")
        return value

    @field_validator("ignore")
    @classmethod
    def ignore_paths_are_dotted(cls, value: list[str]) -> list[str]:
        for pattern in value:
            if any(part == "" for part in pattern.split(".")):
                raise ValueError(f"invalid ignore path: {pattern!r}")
        return value

    @field_validator("ignore_headers")
    @classmethod
    def lowercase_ignore_headers(cls, value: list[str]) -> list[str]:
        return [item.lower() for item in value]

    @model_validator(mode="after")
    def request_ids_are_unique(self) -> Self:
        ids = [item.id for item in self.requests]
        duplicates = sorted({item_id for item_id in ids if ids.count(item_id) > 1})
        if duplicates:
            raise ValueError("duplicate request ids: " + ", ".join(duplicates))
        return self


class Exchange(BaseModel):
    """A sanitized response captured from one request."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    id: str
    method: str
    path: str
    status: int | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    json_body: Any = Field(default=None, alias="json")
    body: str | None = None
    body_encoding: BodyEncoding = "utf-8"
    is_json: bool = False
    error: str | None = None
    elapsed_ms: float | None = None

    @field_validator("headers")
    @classmethod
    def lowercase_header_names(cls, value: dict[str, str]) -> dict[str, str]:
        return {key.lower(): item for key, item in value.items()}

    @model_validator(mode="after")
    def json_flag_matches_payload(self) -> Self:
        if self.is_json and self.body is not None:
            raise ValueError("json responses cannot also set body")
        if not self.is_json and self.json_body is not None:
            raise ValueError("set is_json true when json is present")
        return self


class Baseline(BaseModel):
    """Responses captured from one target, in request-file order."""

    model_config = ConfigDict(extra="forbid")

    name: str
    target: str
    requests_fingerprint: str | None = None
    exchanges: list[Exchange]


class Diff(BaseModel):
    """One concrete difference between a baseline response and a replay."""

    kind: DiffKind
    path: str
    op: DiffOp
    baseline: Any = None
    candidate: Any = None


class CaseResult(BaseModel):
    """The comparison outcome for a single request id."""

    id: str
    method: str
    path: str
    outcome: Outcome
    diffs: list[Diff] = Field(default_factory=list)
    error: str | None = None
    baseline_status: int | None = None
    candidate_status: int | None = None
    baseline_elapsed_ms: float | None = None
    candidate_elapsed_ms: float | None = None


class Summary(BaseModel):
    total: int
    matched: int
    regressed: int
    errored: int


class Report(BaseModel):
    """Deterministic regression report. Downstream tools read this and do not re-diff."""

    name: str
    summary: Summary
    results: list[CaseResult]
