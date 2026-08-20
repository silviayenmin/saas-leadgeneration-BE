from fastapi import APIRouter, Depends, HTTPException
from app.core.security import get_current_user_id
from app.services.credit_service import CreditService
from app.core.config import settings
from app.core.database import db_manager

router = APIRouter()

PLANS = {
    "FREE": {"price": 0, "credits": settings.FREE_CREDITS, "name": "Free"},
    "STARTER": {"price": 29, "credits": settings.STARTER_CREDITS, "name": "Starter"},
    "AGENCY_PRO": {"price": 79, "credits": settings.AGENCY_PRO_CREDITS, "name": "Agency Pro"}
}

@router.get("/plans")
async def get_plans():
    return {"success": True, "data": PLANS}

@router.get("/current")
async def get_current_subscription(user_id: str = Depends(get_current_user_id)):
    credits = CreditService.get_user_credits(user_id)
    return {"success": True, "data": credits}

@router.post("/upgrade")
async def upgrade_plan(plan_key: str, user_id: str = Depends(get_current_user_id)):
    if plan_key not in PLANS:
        raise HTTPException(status_code=400, detail="Invalid plan selected")

    from datetime import datetime
    plan_info = PLANS[plan_key]
    coll_sub = db_manager.get_collection("subscriptions")
    update_data = {
        "plan": plan_key,
        "creditLimit": plan_info["credits"],
        "creditsUsed": 0,
        "updatedAt": datetime.utcnow().isoformat()
    }

    if coll_sub is not None:
        coll_sub.update_one({"userId": user_id}, {"$set": update_data})
    else:
        db_manager.json_db.update_one("subscriptions", {"userId": user_id}, {"$set": update_data})

    return {"success": True, "message": f"Successfully upgraded to {plan_info['name']} plan!", "data": plan_info}
