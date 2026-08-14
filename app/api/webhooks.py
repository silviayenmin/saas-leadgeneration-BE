import uuid
from datetime import datetime
from fastapi import APIRouter, Depends
from app.core.security import get_current_user_id
from app.core.database import db_manager

router = APIRouter()

@router.get("/")
async def get_webhooks(user_id: str = Depends(get_current_user_id)):
    coll = db_manager.get_collection("webhooks")
    if coll is not None:
        hooks = list(coll.find({"userId": user_id}))
    else:
        hooks = db_manager.json_db.find("webhooks", {"userId": user_id})
    return {"success": True, "data": hooks}

@router.post("/create")
async def create_webhook(url: str, eventType: str, user_id: str = Depends(get_current_user_id)):
    webhook = {
        "id": str(uuid.uuid4()),
        "userId": user_id,
        "url": url,
        "eventType": eventType,
        "secret": str(uuid.uuid4())[:16],
        "createdAt": datetime.utcnow().isoformat()
    }
    coll = db_manager.get_collection("webhooks")
    if coll is not None:
        coll.insert_one(webhook)
    else:
        db_manager.json_db.insert_one("webhooks", webhook)

    return {"success": True, "data": webhook}
