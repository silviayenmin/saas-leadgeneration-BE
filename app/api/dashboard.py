from fastapi import APIRouter, Depends
from app.core.security import get_current_user_id
from app.core.database import db_manager
from app.services.credit_service import CreditService

router = APIRouter()

@router.get("/")
async def get_dashboard_data(user_id: str = Depends(get_current_user_id)):
    credits = CreditService.get_user_credits(user_id)

    coll_b = db_manager.get_collection("businesses")
    if coll_b is not None:
        businesses = list(coll_b.find({"userId": user_id}))
    else:
        businesses = db_manager.json_db.find("businesses", {"userId": user_id})

    total_businesses = len(businesses)
    verified_emails = sum(1 for b in businesses if b.get("emails"))
    phone_numbers = sum(1 for b in businesses if b.get("phone"))

    coll_leads = db_manager.get_collection("leads")
    if coll_leads is not None:
        leads = list(coll_leads.find({"userId": user_id}))
    else:
        leads = db_manager.json_db.find("leads", {"userId": user_id})

    ai_pitches = sum(1 for l in leads if l.get("pitch"))

    # Intent Distribution
    intent_counts = {"HIGH": 0, "MEDIUM": 0, "LOW": 0, "UNSCORED": 0}
    for b in businesses:
        intent = b.get("intent", "UNSCORED")
        if intent in intent_counts:
            intent_counts[intent] += 1
        else:
            intent_counts["UNSCORED"] += 1

    return {
        "success": True,
        "data": {
            "credits": credits,
            "kpis": {
                "businessesDiscovered": total_businesses,
                "verifiedEmails": verified_emails,
                "phoneNumbers": phone_numbers,
                "aiPitchesGenerated": ai_pitches
            },
            "intentDistribution": intent_counts,
            "recentLeads": businesses[:10]
        }
    }
