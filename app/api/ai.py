from fastapi import APIRouter, Depends, HTTPException
from app.core.security import get_current_user_id
from app.core.database import db_manager
from app.services.ai_service import AIService
from app.services.credit_service import CreditService
from app.schemas.schemas import ColdPitchRequest
from app.core.config import settings

router = APIRouter()

@router.post("/score")
async def score_lead_ai(business_id: str, provider: str = "groq", user_id: str = Depends(get_current_user_id)):
    coll_b = db_manager.get_collection("businesses")
    if coll_b is not None:
        b = coll_b.find_one({"id": business_id, "userId": user_id})
    else:
        b = db_manager.json_db.find_one("businesses", {"id": business_id, "userId": user_id})

    if not b:
        raise HTTPException(status_code=404, detail="Business not found")

    result = await AIService.score_lead(b, provider=provider)

    # Update business in DB
    if coll_b is not None:
        coll_b.update_one({"id": business_id}, {"$set": {"aiScore": result["score"], "intent": result["intent"], "reasoning": result["reasoning"]}})
    else:
        db_manager.json_db.update_one("businesses", {"id": business_id}, {"$set": {"aiScore": result["score"], "intent": result["intent"], "reasoning": result["reasoning"]}})

    return {"success": True, "data": result}

@router.post("/pitch")
async def generate_pitch_ai(req: ColdPitchRequest, provider: str = "groq", user_id: str = Depends(get_current_user_id)):
    # Deduct Credit
    success, msg, credits_info = CreditService.check_and_deduct(
        user_id=user_id,
        action="AI_PITCH",
        cost=settings.COST_AI_PITCH
    )
    if not success:
        raise HTTPException(status_code=402, detail=msg)

    # Load integrations model configuration
    coll_int = db_manager.get_collection("integrations")
    if coll_int is not None:
        cfg = coll_int.find_one({"userId": user_id}) or {}
    else:
        cfg = db_manager.json_db.find_one("integrations", {"userId": user_id}) or {}

    model_conf = cfg.get("modelConfig") or {}
    active_provider = model_conf.get("active_provider", "groq")
    providers = model_conf.get("providers") or {}
    prov_conf = providers.get(active_provider) or {}

    # Extract dynamic settings
    api_model = prov_conf.get("model")
    api_temp = prov_conf.get("temperature", 0.7)
    api_url = prov_conf.get("base_url")

    coll_b = db_manager.get_collection("businesses")
    if coll_b is not None:
        b = coll_b.find_one({"id": req.businessId, "userId": user_id})
    else:
        b = db_manager.json_db.find_one("businesses", {"id": req.businessId, "userId": user_id})

    if not b:
        raise HTTPException(status_code=404, detail="Business not found")

    pitch = await AIService.generate_cold_pitch(
        b, 
        req.pitchType, 
        provider=active_provider,
        model=api_model,
        temperature=api_temp,
        base_url=api_url
    )

    return {
        "success": True,
        "pitch": pitch,
        "creditsRemaining": credits_info["creditsRemaining"]
    }
