import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from app.schemas.schemas import MapsSearchRequest
from app.core.security import get_current_user_id
from app.core.database import db_manager
from app.services.credit_service import CreditService
from app.services.ai_service import AIService
from app.core.config import settings

router = APIRouter()

@router.post("/search")
async def search_maps(req: MapsSearchRequest, user_id: str = Depends(get_current_user_id)):
    # Deduct Credit
    success, msg, credits_info = CreditService.check_and_deduct(
        user_id=user_id,
        action="MAP_SEARCH",
        cost=settings.COST_MAP_SEARCH
    )
    if not success:
        raise HTTPException(status_code=402, detail=msg)

    # Generated Mock/Scraped local business results tailored to keyword & location
    mock_results = [
        {
            "id": str(uuid.uuid4()),
            "userId": user_id,
            "name": f"Astra {req.keyword.title()} Center",
            "category": req.keyword.title(),
            "address": f"104 Anna Salai, {req.location}",
            "phone": "+91 44 2834 9011",
            "website": f"https://astra{req.keyword.lower().replace(' ', '')}.com",
            "rating": 4.8,
            "reviewCount": 142,
            "latitude": 13.0827,
            "longitude": 80.2707,
            "intent": "HIGH",
            "aiScore": 88,
            "reasoning": "High Google rating with strong review count but outdated website stack."
        },
        {
            "id": str(uuid.uuid4()),
            "userId": user_id,
            "name": f"Prime {req.keyword.title()} & Care",
            "category": req.keyword.title(),
            "address": f"42 T. Nagar Main Rd, {req.location}",
            "phone": "+91 44 4210 5544",
            "website": None,
            "rating": 4.2,
            "reviewCount": 38,
            "latitude": 13.0418,
            "longitude": 80.2341,
            "intent": "HIGH",
            "aiScore": 92,
            "reasoning": "No website registered on Google Maps. High priority lead for web development."
        },
        {
            "id": str(uuid.uuid4()),
            "userId": user_id,
            "name": f"City {req.keyword.title()} Clinic",
            "category": req.keyword.title(),
            "address": f"88 Velachery Main Rd, {req.location}",
            "phone": "+91 44 2243 0088",
            "website": f"https://city{req.keyword.lower().replace(' ', '')}.in",
            "rating": 3.9,
            "reviewCount": 19,
            "latitude": 12.9815,
            "longitude": 80.2180,
            "intent": "MEDIUM",
            "aiScore": 64,
            "reasoning": "Moderate reviews and basic site."
        }
    ]

    # Store businesses in DB
    coll_b = db_manager.get_collection("businesses")
    for b in mock_results:
        if coll_b is not None:
            coll_b.insert_one(b)
        else:
            db_manager.json_db.insert_one("businesses", b)

    # Save Scan record
    scan_record = {
        "id": str(uuid.uuid4()),
        "userId": user_id,
        "keyword": req.keyword,
        "location": req.location,
        "businessesFound": len(mock_results),
        "status": "Completed",
        "createdAt": datetime.utcnow().isoformat()
    }
    coll_s = db_manager.get_collection("map_scans")
    if coll_s is not None:
        coll_s.insert_one(scan_record)
    else:
        db_manager.json_db.insert_one("map_scans", scan_record)

    return {
        "success": True,
        "data": mock_results,
        "creditsRemaining": credits_info["creditsRemaining"]
    }

@router.get("/scans")
async def get_scans(user_id: str = Depends(get_current_user_id)):
    coll_s = db_manager.get_collection("map_scans")
    if coll_s is not None:
        scans = list(coll_s.find({"userId": user_id}))
    else:
        scans = db_manager.json_db.find("map_scans", {"userId": user_id})
    return {"success": True, "data": scans}
