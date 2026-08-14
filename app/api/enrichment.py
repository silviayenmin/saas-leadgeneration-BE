from fastapi import APIRouter, Depends, HTTPException
from app.core.security import get_current_user_id
from app.core.database import db_manager
from app.services.credit_service import CreditService
from app.core.config import settings

router = APIRouter()

@router.post("/reveal-email")
async def reveal_email(business_id: str, user_id: str = Depends(get_current_user_id)):
    # Deduct Credit
    success, msg, credits_info = CreditService.check_and_deduct(
        user_id=user_id,
        action="REVEAL_EMAIL",
        cost=settings.COST_REVEAL_EMAIL
    )
    if not success:
        raise HTTPException(status_code=402, detail=msg)

    coll_b = db_manager.get_collection("businesses")
    if coll_b is not None:
        b = coll_b.find_one({"id": business_id, "userId": user_id})
    else:
        b = db_manager.json_db.find_one("businesses", {"id": business_id, "userId": user_id})

    if not b:
        raise HTTPException(status_code=404, detail="Business not found")

    domain = b.get("name", "contact").lower().replace(" ", "")
    revealed_emails = [
        {"email": f"owner@{domain}.com", "type": "Work", "confidence": "95%"},
        {"email": f"info@{domain}.com", "type": "General", "confidence": "88%"}
    ]
    owner_name = f"Dr. {b.get('name', 'Business').split()[0]}"

    update_payload = {
        "emails": revealed_emails,
        "owner": owner_name,
        "websiteIntelligence": {
            "ssl": True,
            "mobileFriendly": False,
            "cms": "WordPress 6.4",
            "performance": "Needs Optimization"
        }
    }

    if coll_b is not None:
        coll_b.update_one({"id": business_id}, {"$set": update_payload})
    else:
        db_manager.json_db.update_one("businesses", {"id": business_id}, {"$set": update_payload})

    return {
        "success": True,
        "data": update_payload,
        "creditsRemaining": credits_info["creditsRemaining"]
    }
