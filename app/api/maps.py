import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from app.schemas.schemas import MapsSearchRequest
from app.core.security import get_current_user_id
from app.core.database import db_manager, serialize_doc
from app.services.credit_service import CreditService
from app.services.ai_service import AIService
from app.services.google_maps_adapter import GoogleMapsAdapter
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

    # Initialize crawler adapter and run real search
    adapter = GoogleMapsAdapter()
    
    print(f"[Maps API] Launching real Google Maps crawl for keyword='{req.keyword}', location='{req.location}', limit={req.limit}")
    
    try:
        scraped_leads = adapter.search(
            keyword=req.keyword,
            location=req.location,
            limit=req.limit
        )
    except Exception as crawl_exc:
        print(f"[Maps API] Scraping execution failed: {crawl_exc}")
        raise HTTPException(status_code=500, detail=f"Google Maps scraper error: {str(crawl_exc)}")

    results = []
    scan_id = str(uuid.uuid4())
    
    coll_b = db_manager.get_collection("businesses")

    for lead in scraped_leads:
        try:
            rating_val = float(lead["rating"]) if lead["rating"] else 0.0
        except Exception:
            rating_val = 0.0

        try:
            reviews_val = int(lead["reviews"]) if lead["reviews"] else 0
        except Exception:
            reviews_val = 0

        # Construct emails list matching schema
        emails_list = []
        if "emails" in lead and lead["emails"]:
            emails_list = [{"email": e, "type": "Work", "confidence": "80%"} for e in lead["emails"]]
        elif lead.get("meta_contact_info"):
            emails_list = [{"email": lead["meta_contact_info"], "type": "Work", "confidence": "75%"}]

        social_links = {
            "linkedin": lead.get("meta_linkedin") or None,
            "facebook": None,
            "twitter": None
        }

        # Extracted category from lead title or fallback
        category_val = "Business"
        if " - " in lead.get("title", ""):
            parts = lead["title"].split(" - ")
            if len(parts) > 1:
                category_part = parts[1]
                if " in " in category_part:
                    category_val = category_part.split(" in ")[0].strip()
                else:
                    category_val = category_part.strip()

        business_id = str(uuid.uuid4())
        
        business_record = {
            "id": business_id,
            "userId": user_id,
            "scanId": scan_id,
            "name": lead["meta_business_name"],
            "category": category_val,
            "address": lead["meta_address"],
            "phone": lead["phone"] or None,
            "website": lead["meta_website"] or None,
            "rating": rating_val,
            "reviewCount": reviews_val,
            "placeId": lead["link"] or None,
            "latitude": 0.0,
            "longitude": 0.0,
            "openingHours": [],
            "emails": emails_list,
            "owner": lead.get("meta_owner_name") or None,
            "socialLinks": social_links,
            "websiteIntelligence": {
                "description": lead.get("meta_description") or "",
                "foundedYear": str(lead.get("meta_founded_year") or "")
            },
            "contacts": lead.get("meta_contacts") or [],
            "aiScore": 0,
            "intent": "UNSCORED",
            "reasoning": None,
            "createdAt": datetime.utcnow().isoformat()
        }

        # Run AI scoring for the lead
        try:
            ai_score_res = await AIService.score_lead(business_record)
            business_record["aiScore"] = ai_score_res.get("score", 50)
            business_record["intent"] = ai_score_res.get("intent", "UNSCORED")
            business_record["reasoning"] = ai_score_res.get("reasoning", "AI scoring complete.")
        except Exception as ai_err:
            print(f"[Maps API] AI Scoring failed for {lead['meta_business_name']}: {ai_err}")
            business_record["aiScore"] = 50
            business_record["intent"] = "MEDIUM"
            business_record["reasoning"] = "Rule-based score fallback due to AI scoring timeout."

        # Insert business to database
        if coll_b is not None:
            coll_b.insert_one(business_record)
        else:
            db_manager.json_db.insert_one("businesses", business_record)

        if "_id" in business_record:
            business_record.pop("_id")

        results.append(business_record)

    # Save Scan record
    scan_record = {
        "id": scan_id,
        "userId": user_id,
        "keyword": req.keyword,
        "location": req.location,
        "businessesFound": len(results),
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
        "data": results,
        "creditsRemaining": credits_info["creditsRemaining"]
    }

@router.get("/scans")
async def get_scans(user_id: str = Depends(get_current_user_id)):
    coll_s = db_manager.get_collection("map_scans")
    if coll_s is not None:
        scans = list(coll_s.find({"userId": user_id}))
    else:
        scans = db_manager.json_db.find("map_scans", {"userId": user_id})
    return {"success": True, "data": serialize_doc(scans)}

@router.get("/scans/{scan_id}/businesses")
async def get_scan_businesses(scan_id: str, user_id: str = Depends(get_current_user_id)):
    coll_b = db_manager.get_collection("businesses")
    if coll_b is not None:
        items = list(coll_b.find({"scanId": scan_id, "userId": user_id}))
    else:
        items = db_manager.json_db.find("businesses", {"scanId": scan_id, "userId": user_id})
    return {"success": True, "data": serialize_doc(items)}
