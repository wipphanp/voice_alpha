"""Leads API — CRUD operations for customer leads."""

import csv
import io

from fastapi import APIRouter, File, UploadFile
from fastapi.responses import JSONResponse

from app.core.data_store import data_store

router = APIRouter()


@router.get("")
async def get_leads():
    """Return all leads."""
    return data_store.get_leads()


@router.post("/add")
async def add_lead(payload: dict):
    """Add a single lead. Requires name and phone (with +country code)."""
    name = payload.get("name", "").strip()
    phone = payload.get("phone", "").strip()

    if not name or not phone.startswith("+"):
        return JSONResponse(
            {"error": "name + phone (with +country code) required"},
            status_code=400,
        )

    try:
        data_store.add_lead(name, phone)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)

    total = len(data_store.get_leads())
    return {"ok": True, "total": total}


@router.post("/csv")
async def upload_csv(file: UploadFile = File(...)):
    """Bulk upload leads from CSV. Format: name,phone per row."""
    content = (await file.read()).decode("utf-8")
    reader = csv.reader(io.StringIO(content))

    new_leads = []
    for row in reader:
        if len(row) >= 2 and row[1].strip().startswith("+"):
            new_leads.append({"name": row[0].strip(), "phone": row[1].strip()})

    added = data_store.add_leads_bulk(new_leads)
    total = len(data_store.get_leads())
    return {"loaded": added, "total": total}


@router.post("/bulk")
async def add_bulk(payload: dict):
    """Bulk add leads from JSON. Expects {leads: [{name, phone}, ...]}."""
    leads = payload.get("leads", [])
    if not leads:
        return JSONResponse({"error": "leads list required"}, status_code=400)
    added = data_store.add_leads_bulk(leads)
    total = len(data_store.get_leads())
    return {"loaded": added, "total": total}


@router.delete("")
async def clear_leads():
    """Clear all leads."""
    data_store.clear_leads()
    return {"ok": True}


@router.post("/delete")
async def delete_lead(payload: dict):
    """Delete a single lead by phone."""
    phone = payload.get("phone", "").strip()
    if not phone:
        return JSONResponse({"error": "phone required"}, status_code=400)
    data_store.delete_lead(phone)
    return {"ok": True}


@router.post("/delete-batch")
async def delete_leads_batch(payload: dict):
    """Delete multiple leads by phone numbers."""
    phones = payload.get("phones", [])
    if not phones:
        return JSONResponse({"error": "phones list required"}, status_code=400)
    data_store.delete_leads_batch(phones)
    return {"ok": True, "deleted": len(phones)}
