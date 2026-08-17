import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from app.core.security import get_current_user_id
from app.core.database import db_manager
from app.schemas.schemas import LeadPipelineUpdate

router = APIRouter()

@router.get("")
@router.get("/")
async def get_leads(user_id: str = Depends(get_current_user_id)):
    coll = db_manager.get_collection("leads")
    if coll is not None:
        leads = list(coll.find({"userId": user_id}))
    else:
        leads = db_manager.json_db.find("leads", {"userId": user_id})
    return {"success": True, "data": leads}

@router.post("/add")
async def add_to_pipeline(business_id: str, user_id: str = Depends(get_current_user_id)):
    coll_b = db_manager.get_collection("businesses")
    if coll_b is not None:
        b = coll_b.find_one({"id": business_id, "userId": user_id})
    else:
        b = db_manager.json_db.find_one("businesses", {"id": business_id, "userId": user_id})

    if not b:
        raise HTTPException(status_code=404, detail="Business not found")

    lead_item = {
        "id": str(uuid.uuid4()),
        "userId": user_id,
        "businessId": business_id,
        "business": b,
        "stage": "Discovered",
        "pitch": None,
        "notes": "",
        "createdAt": datetime.utcnow().isoformat()
    }

    coll_l = db_manager.get_collection("leads")
    if coll_l is not None:
        coll_l.insert_one(lead_item)
    else:
        db_manager.json_db.insert_one("leads", lead_item)

    return {"success": True, "message": "Lead added to pipeline", "data": lead_item}
