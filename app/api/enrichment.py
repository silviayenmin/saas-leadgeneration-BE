from fastapi import APIRouter, Depends, HTTPException
from app.core.security import get_current_user_id
from app.core.database import db_manager
from app.services.credit_service import CreditService
from app.services.contact_enricher import ContactEnrichmentManager
from app.core.config import settings

router = APIRouter()

def sync_lead_business_details(business_id: str, update_payload: dict):
    """
    Helper function to sync business enrichment updates to the lead documents in CRM.
    """
    coll_l = db_manager.get_collection("leads")
    if coll_l is not None:
        # Update MongoDB leads collection nested business details
        coll_l.update_many(
            {"businessId": business_id}, 
            {"$set": {f"business.{key}": val for key, val in update_payload.items()}}
        )
    else:
        # Update JSON DB leads collection nested business details
        leads = db_manager.json_db.find("leads", {"businessId": business_id})
        for lead in leads:
            if "business" not in lead:
                lead["business"] = {}
            for key, val in update_payload.items():
                lead["business"][key] = val
            db_manager.json_db.update_one(
                "leads", 
                {"id": lead["id"]}, 
                {"$set": {"business": lead["business"]}}
            )

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

    # Run multi-provider fallback enrichment chain
    manager = ContactEnrichmentManager(provider="fallback_chain")
    owner_name = b.get("owner") or ""
    company_name = b.get("name") or ""
    linkedin_url = b.get("socialLinks", {}).get("linkedin")
    
    try:
        enrich_res = manager.enrich(author_name=owner_name, company_name=company_name, linkedin_url=linkedin_url)
    except Exception as ex:
        print(f"[Enrichment API] Email reveal failed: {ex}")
        enrich_res = {}

    email = enrich_res.get("email")
    source = enrich_res.get("contactSource", "none")
    confidence = enrich_res.get("contactConfidence", "none")

    update_payload = {}
    
    if enrich_res.get("companyLinkedin") and not b.get("socialLinks", {}).get("linkedin"):
        social_links = b.get("socialLinks") or {"linkedin": None, "facebook": None, "twitter": None}
        social_links["linkedin"] = enrich_res["companyLinkedin"]
        update_payload["socialLinks"] = social_links
    
    if email:
        existing_emails = b.get("emails") or []
        # Check if already present to prevent duplicate listings
        if not any(item.get("email") == email for item in existing_emails):
            existing_emails.append({
                "email": email,
                "type": "Work",
                "confidence": confidence,
                "source": source
            })
        update_payload["emails"] = existing_emails
        
        if enrich_res.get("authorName") and not b.get("owner"):
            update_payload["owner"] = enrich_res["authorName"]

        # Save metadata enhancements (e.g. employeeCount, annualRevenue, foundedYear)
        intel = b.get("websiteIntelligence") or {}
        if enrich_res.get("employeeCount"):
            intel["employeeCount"] = enrich_res["employeeCount"]
        if enrich_res.get("annualRevenue"):
            intel["annualRevenue"] = enrich_res["annualRevenue"]
        if enrich_res.get("foundedYear") and not intel.get("foundedYear"):
            intel["foundedYear"] = enrich_res["foundedYear"]
            
        update_payload["websiteIntelligence"] = intel

        if enrich_res.get("industry") and not b.get("category"):
            update_payload["category"] = enrich_res["industry"]

    if update_payload:
        # Update database businesses collection
        if coll_b is not None:
            coll_b.update_one({"id": business_id}, {"$set": update_payload})
        else:
            db_manager.json_db.update_one("businesses", {"id": business_id}, {"$set": update_payload})

        # Sync changes to CRM leads snapshot
        sync_lead_business_details(business_id, update_payload)

    # Prepare response data
    updated_emails = update_payload.get("emails", b.get("emails") or [])
    updated_owner = update_payload.get("owner", b.get("owner"))
    updated_intel = update_payload.get("websiteIntelligence", b.get("websiteIntelligence") or {})
    updated_socials = update_payload.get("socialLinks", b.get("socialLinks") or {})

    return {
        "success": True,
        "data": {
            "emails": updated_emails,
            "owner": updated_owner,
            "websiteIntelligence": updated_intel,
            "socialLinks": updated_socials
        },
        "creditsRemaining": credits_info["creditsRemaining"]
    }

@router.post("/find-team")
async def find_team(business_id: str, user_id: str = Depends(get_current_user_id)):
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

    # Run team enrichment using Apollo/Serper fallback
    manager = ContactEnrichmentManager(provider="fallback_chain")
    owner_name = b.get("owner") or ""
    company_name = b.get("name") or ""
    linkedin_url = b.get("socialLinks", {}).get("linkedin")
    
    try:
        enrich_res = manager.enrich_team(
            author_name=owner_name,
            company_name=company_name,
            linkedin_url=linkedin_url
        )
    except Exception as ex:
        print(f"[Enrichment API] Find team failed: {ex}")
        enrich_res = {}

    key_contacts = enrich_res.get("keyContacts", [])
    source = enrich_res.get("contactSource", "none")

    update_payload = {
        "contacts": key_contacts,
        "contactsSource": source
    }
    
    if enrich_res.get("companyLinkedin") and not b.get("socialLinks", {}).get("linkedin"):
        social_links = b.get("socialLinks") or {"linkedin": None, "facebook": None, "twitter": None}
        social_links["linkedin"] = enrich_res["companyLinkedin"]
        update_payload["socialLinks"] = social_links

    if enrich_res.get("email"):
        existing_emails = b.get("emails") or []
        if not any(item.get("email") == enrich_res["email"] for item in existing_emails):
            existing_emails.append({
                "email": enrich_res["email"],
                "type": "Work",
                "confidence": enrich_res.get("contactConfidence") or "high",
                "source": source
            })
        update_payload["emails"] = existing_emails

    if enrich_res.get("authorName") and not b.get("owner"):
        update_payload["owner"] = enrich_res["authorName"]

    # Save to DB businesses collection
    if coll_b is not None:
        coll_b.update_one({"id": business_id}, {"$set": update_payload})
    else:
        db_manager.json_db.update_one("businesses", {"id": business_id}, {"$set": update_payload})

    # Sync changes to CRM leads snapshot
    sync_lead_business_details(business_id, update_payload)

    return {
        "success": True,
        "data": {
            "contacts": key_contacts,
            "contactsSource": source,
            "emails": update_payload.get("emails", b.get("emails") or []),
            "socialLinks": update_payload.get("socialLinks", b.get("socialLinks") or {})
        },
        "creditsRemaining": credits_info["creditsRemaining"]
    }

from pydantic import BaseModel
from app.services.contact_enricher import extract_domain

class EnrichTeamRequest(BaseModel):
    sourceUrl: str

@router.post("/enrich-team")
async def enrich_team_route(req: EnrichTeamRequest, user_id: str = Depends(get_current_user_id)):
    source_url = req.sourceUrl.strip()
    
    # 1. Caching logic: First, look up the lead in the database.
    coll_b = db_manager.get_collection("businesses")
    b = None
    if coll_b is not None:
        b = coll_b.find_one({
            "$or": [
                {"website": source_url},
                {"placeId": source_url},
                {"website": source_url.rstrip("/")},
                {"placeId": source_url.rstrip("/")}
            ],
            "userId": user_id
        })
    else:
        for biz in db_manager.json_db.find("businesses", {"userId": user_id}):
            if biz.get("website") == source_url or biz.get("placeId") == source_url or biz.get("website") == source_url.rstrip("/") or biz.get("placeId") == source_url.rstrip("/"):
                b = biz
                break
                
    if not b:
        # Fallback: search by domain or name
        cleaned_domain = extract_domain(source_url)
        if cleaned_domain:
            if coll_b is not None:
                b = coll_b.find_one({
                    "website": {"$regex": cleaned_domain, "$options": "i"},
                    "userId": user_id
                })
            else:
                for biz in db_manager.json_db.find("businesses", {"userId": user_id}):
                    if biz.get("website") and cleaned_domain in biz.get("website").lower():
                        b = biz
                        break
                        
    if not b:
        raise HTTPException(status_code=404, detail="Business not found in database for the given sourceUrl")

    # Format location
    address = b.get("address") or ""
    location = "Not Specified"
    if address:
        parts = [p.strip() for p in address.split(",") if p.strip()]
        if len(parts) >= 2:
            location = f"{parts[-2]}, {parts[-1]}"
            import re
            location = re.sub(r"\b\d{6}\b", "", location).strip().rstrip(",")
        else:
            location = address

    # If keyContacts is already populated and has elements, return it immediately to avoid wasting API credits.
    if b.get("contacts") and len(b["contacts"]) > 0:
        print(f"[Enrich Team Cache] Cache hit for business '{b.get('name')}'. Returning cached team contacts.")
        return {
            "status": "success",
            "companyName": b.get("name") or "",
            "industry": b.get("category") or "Not Specified",
            "location": location,
            "employeeCount": b.get("employeeCount") or (b.get("websiteIntelligence") or {}).get("employeeCount") or "1-50 employees",
            "foundedYear": b.get("websiteIntelligence", {}).get("foundedYear") or b.get("foundedYear") or None,
            "annualRevenue": b.get("websiteIntelligence", {}).get("annualRevenue") or b.get("annualRevenue") or None,
            "totalFunding": b.get("websiteIntelligence", {}).get("totalFunding") or b.get("totalFunding") or None,
            "keyContacts": b["contacts"],
            "keyContactsSource": b.get("contactsSource") or "cache"
        }

    # Deduct Credit
    success, msg, credits_info = CreditService.check_and_deduct(
        user_id=user_id,
        action="REVEAL_EMAIL",
        cost=settings.COST_REVEAL_EMAIL
    )
    if not success:
        raise HTTPException(status_code=402, detail=msg)

    # Proceed with enrichment
    manager = ContactEnrichmentManager(provider="fallback_chain")
    owner_name = b.get("owner") or ""
    company_name = b.get("name") or ""
    linkedin_url = b.get("socialLinks", {}).get("linkedin")
    company_domain = extract_domain(b.get("website"))

    try:
        enrich_res = manager.enrich_team(
            author_name=owner_name,
            company_name=company_name,
            linkedin_url=linkedin_url,
            company_domain=company_domain
        )
    except Exception as ex:
        print(f"[Enrichment API] /enrich-team failed: {ex}")
        enrich_res = {}

    key_contacts = enrich_res.get("keyContacts", [])
    source = enrich_res.get("contactSource", "none")

    # Update metadata variables based on Apollo or DB fallback
    employee_count = enrich_res.get("employeeCount") or b.get("employeeCount") or (b.get("websiteIntelligence") or {}).get("employeeCount") or "1-50 employees"
    founded_year = enrich_res.get("foundedYear") or b.get("websiteIntelligence", {}).get("foundedYear") or b.get("foundedYear") or None
    annual_revenue = enrich_res.get("annualRevenue") or b.get("websiteIntelligence", {}).get("annualRevenue") or b.get("annualRevenue") or None
    total_funding = enrich_res.get("totalFunding") or b.get("websiteIntelligence", {}).get("totalFunding") or b.get("totalFunding") or None
    industry = enrich_res.get("industry") or b.get("category") or "Not Specified"

    update_payload = {
        "contacts": key_contacts,
        "contactsSource": source,
        "employeeCount": employee_count,
        "foundedYear": founded_year,
        "annualRevenue": annual_revenue,
        "totalFunding": total_funding
    }
    
    if enrich_res.get("companyLinkedin") and not b.get("socialLinks", {}).get("linkedin"):
        social_links = b.get("socialLinks") or {"linkedin": None, "facebook": None, "twitter": None}
        social_links["linkedin"] = enrich_res["companyLinkedin"]
        update_payload["socialLinks"] = social_links

    if enrich_res.get("email"):
        existing_emails = b.get("emails") or []
        if not any(item.get("email") == enrich_res["email"] for item in existing_emails):
            existing_emails.append({
                "email": enrich_res["email"],
                "type": "Work",
                "confidence": enrich_res.get("contactConfidence") or "high",
                "source": source
            })
        update_payload["emails"] = existing_emails

    if enrich_res.get("authorName") and not b.get("owner"):
        update_payload["owner"] = enrich_res["authorName"]

    # Save to DB businesses collection
    if coll_b is not None:
        coll_b.update_one({"id": b["id"]}, {"$set": update_payload})
    else:
        db_manager.json_db.update_one("businesses", {"id": b["id"]}, {"$set": update_payload})

    # Sync changes to CRM leads snapshot
    sync_lead_business_details(b["id"], update_payload)

    return {
        "status": "success",
        "companyName": company_name,
        "industry": industry,
        "location": location,
        "employeeCount": employee_count,
        "foundedYear": founded_year,
        "annualRevenue": annual_revenue,
        "totalFunding": total_funding,
        "keyContacts": key_contacts,
        "keyContactsSource": source
    }
