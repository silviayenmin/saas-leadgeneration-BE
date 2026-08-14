from fastapi import APIRouter, Depends
from app.core.security import get_current_user_id
from app.schemas.schemas import IntegrationConfigUpdate
from app.core.database import db_manager

router = APIRouter()

@router.get("/")
async def get_integrations(user_id: str = Depends(get_current_user_id)):
    coll = db_manager.get_collection("integrations")
    if coll is not None:
        cfg = coll.find_one({"userId": user_id})
    else:
        cfg = db_manager.json_db.find_one("integrations", {"userId": user_id})

    if not cfg:
        cfg = {
            "userId": user_id,
            "googlePlacesApiKey": "",
            "serperApiKey": "",
            "aiProvider": "groq",
            "smtpHost": "",
            "smtpPort": 587,
            "smtpUsername": "",
            "smtpPassword": "",
            "imapHost": "",
            "imapPort": 993,
            "imapUsername": "",
            "imapPassword": ""
        }
    else:
        # Mask sensitive keys
        if cfg.get("googlePlacesApiKey"):
            cfg["googlePlacesApiKey"] = "************" + cfg["googlePlacesApiKey"][-4:]
        if cfg.get("serperApiKey"):
            cfg["serperApiKey"] = "************" + cfg["serperApiKey"][-4:]

    return {"success": True, "data": cfg}

@router.post("/update")
async def update_integrations(payload: IntegrationConfigUpdate, user_id: str = Depends(get_current_user_id)):
    update_data = payload.dict(exclude_unset=True)
    coll = db_manager.get_collection("integrations")
    if coll is not None:
        coll.update_one({"userId": user_id}, {"$set": update_data}, upsert=True)
    else:
        existing = db_manager.json_db.find_one("integrations", {"userId": user_id})
        if existing:
            db_manager.json_db.update_one("integrations", {"userId": user_id}, {"$set": update_data})
        else:
            update_data["userId"] = user_id
            db_manager.json_db.insert_one("integrations", update_data)

    return {"success": True, "message": "Integrations updated successfully"}
