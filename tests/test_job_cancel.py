from __future__ import annotations
import pytest
from datetime import datetime, timezone
from backend.database import crud

@pytest.mark.asyncio
async def test_cancel_pending_job(client, db_session):
    doc = await crud.create_document(db_session, id="d1", filename="f.pdf",
        format=".pdf", file_path="/tmp/f.pdf", file_size=100, status="uploaded",
        upload_date=datetime(2025, 3, 1, tzinfo=timezone.utc),
        updated_at=datetime(2025, 3, 1, tzinfo=timezone.utc))
    job = await crud.create_job(db_session, id="j1", document_id="d1",
        job_type="ocr", status="pending", progress=0.0)
    await db_session.commit()
    resp = await client.post("/api/jobs/j1/cancel")
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelling"
    await db_session.refresh(job)
    assert job.status == "cancelling"

@pytest.mark.asyncio
async def test_cancel_running_job(client, db_session):
    await crud.create_document(db_session, id="d1", filename="f.pdf",
        format=".pdf", file_path="/tmp/f.pdf", file_size=100, status="uploaded",
        upload_date=datetime(2025, 3, 1, tzinfo=timezone.utc),
        updated_at=datetime(2025, 3, 1, tzinfo=timezone.utc))
    job = await crud.create_job(db_session, id="j1", document_id="d1",
        job_type="ocr", status="running", progress=0.5)
    await db_session.commit()
    resp = await client.post("/api/jobs/j1/cancel")
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelling"
    await db_session.refresh(job)
    assert job.status == "cancelling"

@pytest.mark.asyncio
async def test_cancel_completed_job_returns_400(client, db_session):
    await crud.create_document(db_session, id="d1", filename="f.pdf",
        format=".pdf", file_path="/tmp/f.pdf", file_size=100, status="completed",
        upload_date=datetime(2025, 3, 1, tzinfo=timezone.utc),
        updated_at=datetime(2025, 3, 1, tzinfo=timezone.utc))
    await crud.create_job(db_session, id="j1", document_id="d1",
        job_type="ocr", status="completed", progress=1.0)
    await db_session.commit()
    resp = await client.post("/api/jobs/j1/cancel")
    assert resp.status_code == 400

@pytest.mark.asyncio
async def test_cancel_failed_job_returns_400(client, db_session):
    await crud.create_document(db_session, id="d1", filename="f.pdf",
        format=".pdf", file_path="/tmp/f.pdf", file_size=100, status="failed",
        upload_date=datetime(2025, 3, 1, tzinfo=timezone.utc),
        updated_at=datetime(2025, 3, 1, tzinfo=timezone.utc))
    await crud.create_job(db_session, id="j1", document_id="d1",
        job_type="ocr", status="failed", progress=0.1)
    await db_session.commit()
    resp = await client.post("/api/jobs/j1/cancel")
    assert resp.status_code == 400

@pytest.mark.asyncio
async def test_cancel_already_cancelling_returns_400(client, db_session):
    await crud.create_document(db_session, id="d1", filename="f.pdf",
        format=".pdf", file_path="/tmp/f.pdf", file_size=100, status="uploaded",
        upload_date=datetime(2025, 3, 1, tzinfo=timezone.utc),
        updated_at=datetime(2025, 3, 1, tzinfo=timezone.utc))
    await crud.create_job(db_session, id="j1", document_id="d1",
        job_type="ocr", status="cancelling", progress=0.3)
    await db_session.commit()
    resp = await client.post("/api/jobs/j1/cancel")
    assert resp.status_code == 400

@pytest.mark.asyncio
async def test_cancel_unknown_job_returns_404(client, db_session):
    resp = await client.post("/api/jobs/nonexistent/cancel")
    assert resp.status_code == 404
