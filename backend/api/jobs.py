from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.crud import get_job, get_jobs_for_document
from backend.database.engine import get_db
from backend.schemas.jobs import JobListResponse, JobResponse

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("/{job_id}", response_model=JobResponse)
async def get_job_endpoint(
    job_id: str,
    db: AsyncSession = Depends(get_db),
) -> JobResponse:
    job = await get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobResponse.model_validate(job)


@router.get("/document/{document_id}", response_model=JobListResponse)
async def get_jobs_for_document_endpoint(
    document_id: str,
    db: AsyncSession = Depends(get_db),
) -> JobListResponse:
    jobs = await get_jobs_for_document(db, document_id)
    return JobListResponse(jobs=[JobResponse.model_validate(j) for j in jobs])
