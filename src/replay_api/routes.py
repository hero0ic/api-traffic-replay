"""HTTP routes. One FastAPI app, one process, no microservice split."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from replay_api.auth import generate_token, get_project_for_token, hash_token
from replay_api.db import get_db
from replay_api.diagnose import NoRegressionsError, build_diagnosis_prompt
from replay_api.llm import LLMError, resolve_provider
from replay_api.models import (
    BaselineRecord,
    Diagnosis,
    Project,
    ReportRecord,
    RequestCollectionRecord,
    Run,
)
from replay_api.schemas import (
    BaselineCreate,
    BaselineCreated,
    CollectionCreated,
    DiagnosisOut,
    ProjectCreate,
    ProjectCreated,
    ProjectOut,
    RunCreate,
    RunDetail,
    RunSummary,
)
from replay_api.slug import slugify
from replay_core.models import RequestCollection

router = APIRouter(prefix="/v1")


@router.post("/projects", response_model=ProjectCreated, status_code=status.HTTP_201_CREATED)
def create_project(body: ProjectCreate, db: Session = Depends(get_db)) -> ProjectCreated:
    token = generate_token()
    project = Project(name=body.name.strip(), slug=slugify(body.name), token_hash=hash_token(token))
    db.add(project)
    db.commit()
    db.refresh(project)
    return ProjectCreated(
        id=project.id,
        name=project.name,
        slug=project.slug,
        token=token,
        created_at=project.created_at,
    )


@router.get("/projects/{project_id}", response_model=ProjectOut)
def get_project(project: Project = Depends(get_project_for_token)) -> Project:
    return project


@router.post(
    "/projects/{project_id}/collections",
    response_model=CollectionCreated,
    status_code=status.HTTP_201_CREATED,
)
def create_collection(
    body: RequestCollection,
    project: Project = Depends(get_project_for_token),
    db: Session = Depends(get_db),
) -> CollectionCreated:
    record = RequestCollectionRecord(
        project_id=project.id,
        name=body.name,
        payload=body.model_dump(mode="json", by_alias=True),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return CollectionCreated(
        id=record.id,
        project_id=record.project_id,
        name=record.name,
        created_at=record.created_at,
    )


@router.post(
    "/projects/{project_id}/baselines",
    response_model=BaselineCreated,
    status_code=status.HTTP_201_CREATED,
)
def create_baseline(
    body: BaselineCreate,
    project: Project = Depends(get_project_for_token),
    db: Session = Depends(get_db),
) -> BaselineCreated:
    if body.collection_id is not None:
        _require_project_collection(db, project.id, body.collection_id)
    record = BaselineRecord(
        project_id=project.id,
        collection_id=body.collection_id,
        name=body.baseline.name,
        target=body.baseline.target,
        payload=body.baseline.model_dump(mode="json", by_alias=True),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return BaselineCreated(
        id=record.id,
        project_id=record.project_id,
        collection_id=record.collection_id,
        name=record.name,
        target=record.target,
        created_at=record.created_at,
    )


@router.post(
    "/projects/{project_id}/runs",
    response_model=RunDetail,
    status_code=status.HTTP_201_CREATED,
)
def create_run(
    body: RunCreate,
    project: Project = Depends(get_project_for_token),
    db: Session = Depends(get_db),
) -> RunDetail:
    if body.collection_id is not None:
        _require_project_collection(db, project.id, body.collection_id)
    if body.baseline_id is not None:
        _require_project_baseline(db, project.id, body.baseline_id)

    summary = body.report.summary
    run = Run(
        project_id=project.id,
        collection_id=body.collection_id,
        baseline_id=body.baseline_id,
        name=body.report.name,
        target=body.target,
        total=summary.total,
        matched=summary.matched,
        regressed=summary.regressed,
        errored=summary.errored,
    )
    db.add(run)
    db.flush()
    report = ReportRecord(
        run_id=run.id,
        payload=body.report.model_dump(mode="json", by_alias=True),
    )
    db.add(report)
    db.commit()
    db.refresh(run)
    db.refresh(report)
    return _run_detail(run, report.payload, diagnosis=None)


@router.get("/projects/{project_id}/runs", response_model=list[RunSummary])
def list_runs(
    project: Project = Depends(get_project_for_token),
    db: Session = Depends(get_db),
) -> list[Run]:
    rows = db.scalars(
        select(Run).where(Run.project_id == project.id).order_by(Run.created_at.desc())
    ).all()
    return list(rows)


@router.get("/projects/{project_id}/runs/{run_id}", response_model=RunDetail)
def get_project_run(
    run_id: UUID,
    project: Project = Depends(get_project_for_token),
    db: Session = Depends(get_db),
) -> RunDetail:
    run = _load_run(db, project.id, run_id)
    return _run_detail(run, run.report.payload, diagnosis=run.diagnosis)


@router.post(
    "/projects/{project_id}/runs/{run_id}/diagnose",
    response_model=DiagnosisOut,
    status_code=status.HTTP_201_CREATED,
)
def diagnose_run(
    run_id: UUID,
    project: Project = Depends(get_project_for_token),
    db: Session = Depends(get_db),
) -> Diagnosis:
    """Ask the model to narrate stored regressions. Does not re-diff responses."""

    run = _load_run(db, project.id, run_id)
    try:
        prompt = build_diagnosis_prompt(run.report.payload)
    except NoRegressionsError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    try:
        # Tests may inject FakeProvider via set_provider_override even when LLM is off.
        provider = resolve_provider()
        content = provider.complete(prompt["messages"])
    except LLMError as exc:
        detail = str(exc)
        code = (
            status.HTTP_503_SERVICE_UNAVAILABLE
            if "disabled" in detail.lower()
            else status.HTTP_502_BAD_GATEWAY
        )
        if code == status.HTTP_503_SERVICE_UNAVAILABLE:
            detail = "AI diagnosis is disabled on this server"
        raise HTTPException(status_code=code, detail=detail) from exc

    existing = run.diagnosis
    if existing is None:
        existing = Diagnosis(run_id=run.id)
        db.add(existing)
    existing.provider = provider.name
    existing.model = provider.model
    existing.prompt_version = prompt["prompt_version"]
    existing.content = content
    db.commit()
    db.refresh(existing)
    return existing


@router.get(
    "/projects/{project_id}/runs/{run_id}/diagnosis",
    response_model=DiagnosisOut,
)
def get_diagnosis(
    run_id: UUID,
    project: Project = Depends(get_project_for_token),
    db: Session = Depends(get_db),
) -> Diagnosis:
    run = _load_run(db, project.id, run_id)
    if run.diagnosis is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="diagnosis not found")
    return run.diagnosis


def _load_run(db: Session, project_id: UUID, run_id: UUID) -> Run:
    run = db.scalar(
        select(Run)
        .options(joinedload(Run.report), joinedload(Run.diagnosis))
        .where(Run.id == run_id, Run.project_id == project_id)
    )
    if run is None or run.report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run not found")
    return run


def _run_detail(run: Run, payload: dict, *, diagnosis: Diagnosis | None) -> RunDetail:
    return RunDetail(
        id=run.id,
        project_id=run.project_id,
        collection_id=run.collection_id,
        baseline_id=run.baseline_id,
        name=run.name,
        target=run.target,
        total=run.total,
        matched=run.matched,
        regressed=run.regressed,
        errored=run.errored,
        created_at=run.created_at,
        report=payload,
        diagnosis=DiagnosisOut.model_validate(diagnosis) if diagnosis is not None else None,
    )


def _require_project_collection(db: Session, project_id: UUID, collection_id: UUID) -> None:
    row = db.get(RequestCollectionRecord, collection_id)
    if row is None or row.project_id != project_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="collection not found")


def _require_project_baseline(db: Session, project_id: UUID, baseline_id: UUID) -> None:
    row = db.get(BaselineRecord, baseline_id)
    if row is None or row.project_id != project_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="baseline not found")
