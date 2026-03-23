# tests/test_templates_api.py
from __future__ import annotations

import pytest
from httpx import AsyncClient


def _sample_fields():
    return [
        {"field_path": "anchor.invoice_number", "display_name": "Invoice Number", "include": True},
        {"field_path": "anchor.total_amount", "display_name": "Total", "include": True},
    ]


@pytest.mark.asyncio
async def test_list_templates_empty(client: AsyncClient):
    """GET /api/templates returns empty list initially."""
    resp = await client.get("/api/templates")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_create_template(client: AsyncClient):
    """POST /api/templates creates a template, returns 201."""
    payload = {
        "name": "Invoice Summary",
        "description": "Key invoice fields",
        "fields": _sample_fields(),
    }
    resp = await client.post("/api/templates", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Invoice Summary"
    assert data["description"] == "Key invoice fields"
    assert len(data["fields"]) == 2
    assert data["fields"][0]["field_path"] == "anchor.invoice_number"
    assert data["fields"][0]["display_name"] == "Invoice Number"
    assert "id" in data
    assert "created_at" in data
    assert "updated_at" in data


@pytest.mark.asyncio
async def test_create_template_duplicate_name(client: AsyncClient):
    """POST with duplicate name returns 409."""
    payload = {
        "name": "My Template",
        "fields": _sample_fields(),
    }
    resp1 = await client.post("/api/templates", json=payload)
    assert resp1.status_code == 201

    resp2 = await client.post("/api/templates", json=payload)
    assert resp2.status_code == 409


@pytest.mark.asyncio
async def test_get_template_by_id(client: AsyncClient):
    """GET /api/templates/{id} returns the template."""
    payload = {
        "name": "Detail Template",
        "fields": _sample_fields(),
    }
    create_resp = await client.post("/api/templates", json=payload)
    assert create_resp.status_code == 201
    template_id = create_resp.json()["id"]

    resp = await client.get(f"/api/templates/{template_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == template_id
    assert data["name"] == "Detail Template"
    assert len(data["fields"]) == 2


@pytest.mark.asyncio
async def test_get_template_not_found(client: AsyncClient):
    """GET /api/templates/{id} returns 404 for unknown id."""
    resp = await client.get("/api/templates/nonexistent-id")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_template(client: AsyncClient):
    """PUT /api/templates/{id} updates the template name."""
    payload = {
        "name": "Original Name",
        "fields": _sample_fields(),
    }
    create_resp = await client.post("/api/templates", json=payload)
    assert create_resp.status_code == 201
    template_id = create_resp.json()["id"]

    update_payload = {"name": "Updated Name"}
    resp = await client.put(f"/api/templates/{template_id}", json=update_payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Updated Name"
    # Fields should be unchanged
    assert len(data["fields"]) == 2


@pytest.mark.asyncio
async def test_update_template_not_found(client: AsyncClient):
    """PUT /api/templates/{id} returns 404 for unknown id."""
    resp = await client.put("/api/templates/nonexistent-id", json={"name": "X"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_template(client: AsyncClient):
    """DELETE /api/templates/{id} returns 204 and template is gone."""
    payload = {
        "name": "To Delete",
        "fields": _sample_fields(),
    }
    create_resp = await client.post("/api/templates", json=payload)
    assert create_resp.status_code == 201
    template_id = create_resp.json()["id"]

    resp = await client.delete(f"/api/templates/{template_id}")
    assert resp.status_code == 204

    # Verify it's gone
    resp2 = await client.get(f"/api/templates/{template_id}")
    assert resp2.status_code == 404


@pytest.mark.asyncio
async def test_delete_template_not_found(client: AsyncClient):
    """DELETE /api/templates/{id} returns 404 for unknown id."""
    resp = await client.delete("/api/templates/nonexistent-id")
    assert resp.status_code == 404
