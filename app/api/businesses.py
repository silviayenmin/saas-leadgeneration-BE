from fastapi import APIRouter, Depends, HTTPException
from app.core.security import get_current_user_id
from app.core.database import db_manager, serialize_doc

router = APIRouter()

@router.get("")
@router.get("/")
async def get_businesses(user_id: str = Depends(get_current_user_id)):
    coll = db_manager.get_collection("businesses")
    if coll is not None:
        items = list(coll.find({"userId": user_id}))
    else:
        items = db_manager.json_db.find("businesses", {"userId": user_id})
    return {"success": True, "data": serialize_doc(items)}

@router.get("/{business_id}")
async def get_business_detail(business_id: str, user_id: str = Depends(get_current_user_id)):
    coll = db_manager.get_collection("businesses")
    if coll is not None:
        item = coll.find_one({"id": business_id, "userId": user_id})
    else:
        item = db_manager.json_db.find_one("businesses", {"id": business_id, "userId": user_id})

    if not item:
        raise HTTPException(status_code=404, detail="Business lead not found")

    return {"success": True, "data": serialize_doc(item)}
