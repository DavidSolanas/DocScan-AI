from datetime import datetime

from pydantic import BaseModel


class JobResponse(BaseModel):
    id: str
    document_id: str
    job_type: str
    status: str
    progress: float
    result: str | None
    error: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None

    model_config = {"from_attributes": True}


class JobListResponse(BaseModel):
    jobs: list[JobResponse]
