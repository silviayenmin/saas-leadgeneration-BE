from fastapi import APIRouter, Depends, HTTPException
from app.core.security import get_current_user_id
from app.schemas.schemas import OnboardingStep1, OnboardingStep2, OnboardingStep3, UserProfileUpdate
from app.core.database import db_manager

router = APIRouter()

@router.get("/me")
def get_current_user(user_id: str = Depends(get_current_user_id)):
    coll = db_manager.get_collection("users")
    if coll is not None:
        user = coll.find_one({"id": user_id})
    else:
        user = db_manager.json_db.find_one("users", {"id": user_id})

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.pop("passwordHash", None)
    return {"success": True, "data": user}

@router.post("/onboarding")
def complete_onboarding(
    step1: OnboardingStep1,
    step2: OnboardingStep2,
    step3: OnboardingStep3,
    user_id: str = Depends(get_current_user_id)
):
    update_payload = {
        "fullName": step1.fullName,
        "phone": step1.phone,
        "jobTitle": step1.jobTitle,
        "companyName": step2.companyName,
        "companyWebsite": step2.companyWebsite,
        "targetIndustry": step2.targetIndustry,
        "targetCities": step3.targetCities,
        "targetBusinessTypes": step3.targetBusinessTypes,
        "onboardingCompleted": True
    }

    coll = db_manager.get_collection("users")
    if coll is not None:
        coll.update_one({"id": user_id}, {"$set": update_payload})
    else:
        db_manager.json_db.update_one("users", {"id": user_id}, {"$set": update_payload})

    return {"success": True, "message": "Onboarding completed successfully"}
