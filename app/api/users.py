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
    if "_id" in user:
        user["_id"] = str(user["_id"])
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
        "location": step1.location,
        "bio": step1.bio,
        "companyName": step2.companyName,
        "companyWebsite": step2.companyWebsite,
        "targetIndustry": step2.targetIndustry,
        "servicesOffered": step2.servicesOffered,
        "technologiesUsed": step2.technologiesUsed,
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

@router.put("/profile")
def update_profile(profile_data: UserProfileUpdate, user_id: str = Depends(get_current_user_id)):
    coll = db_manager.get_collection("users")
    
    update_dict = {k: v for k, v in profile_data.dict(exclude_unset=True).items() if v is not None}
    if not update_dict:
        raise HTTPException(status_code=400, detail="No valid profile fields provided for update")

    if "company" in update_dict:
        update_dict["companyName"] = update_dict["company"]
    elif "companyName" in update_dict:
        update_dict["company"] = update_dict["companyName"]

    if "website" in update_dict:
        update_dict["companyWebsite"] = update_dict["website"]
    elif "companyWebsite" in update_dict:
        update_dict["website"] = update_dict["companyWebsite"]

    if coll is not None:
        coll.update_one({"id": user_id}, {"$set": update_dict})
        updated_user = coll.find_one({"id": user_id})
    else:
        db_manager.json_db.update_one("users", {"id": user_id}, {"$set": update_dict})
        updated_user = db_manager.json_db.find_one("users", {"id": user_id})

    if updated_user:
        updated_user.pop("passwordHash", None)
        if "_id" in updated_user:
            updated_user["_id"] = str(updated_user["_id"])

    return {"success": True, "message": "Profile updated successfully!", "data": updated_user}

