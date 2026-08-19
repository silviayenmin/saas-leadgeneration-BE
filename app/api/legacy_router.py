import time
import uuid
import datetime
import asyncio
from typing import List, Optional
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Request

from app.core.security import get_current_user_id
from app.core.database import db_manager
from app.core.config import settings
from app.services.credit_service import CreditService

# Import Search Adapters
from app.search import get_adapter
from app.search.query_generator import IntentQueryGenerator
from app.search.website_crawler import crawl_website_for_founded_year

# Import Qualification Logic
from app.qualification import classify_lead_intent, calculate_lead_score, is_empty_value
from app.qualification.lead_scoring import validate_author_name, validate_company_name

# Import B2B Enrichment
from app.enrichment.contact_enrichment import ContactEnrichmentManager

# Helper imports for location match and fallback author
import re
import urllib.parse as urlparse

def is_facebook_fallback_name(author_name: str, url: str) -> bool:
    if not url or "facebook.com" not in url.lower() or not author_name:
        return False
    fb_username = ""
    url_lower = url.lower()
    try:
        if "/groups/" in url_lower:
            idx = url_lower.find("facebook.com/groups/")
            if idx != -1:
                part_after = url[idx + len("facebook.com/groups/"):]
                fb_username = part_after.split("/")[0].split("?")[0].strip()
        else:
            idx = url_lower.find("facebook.com/")
            if idx != -1:
                part_after = url[idx + len("facebook.com/"):]
                segment = part_after.split("/")[0].split("?")[0].strip()
                if segment and segment not in ["posts", "photos", "videos", "watch", "share", "groups", "pages", "events"]:
                    fb_username = segment
    except Exception:
        pass

    if not fb_username:
        return False

    split_camel = re.sub(r'(?<!^)(?=[A-Z])', ' ', fb_username)
    username_clean = split_camel.replace("-", " ").replace(".", " ").replace("_", " ")
    words = username_clean.split()
    cleaned_words = []
    for w in words:
        clean_w = "".join(c for c in w if c.isalpha())
        if clean_w:
            cleaned_words.append(clean_w.capitalize())
    
    cleaned_fallback = " ".join(cleaned_words)
    return author_name.lower().strip() == cleaned_fallback.lower().strip()

def extract_author_from_email_or_url(email_val: str, url_val: str) -> str:
    if email_val and "@" in email_val:
        try:
            username = email_val.split("@")[0].strip()
            generic_usernames = {"info", "contact", "admin", "hello", "support", "sales", "jobs", "team", "office", "marketing", "hr", "careers", "staff", "inbox"}
            if username.lower() not in generic_usernames:
                cleaned = username.replace(".", " ").replace("-", " ").replace("_", " ")
                words = cleaned.split()
                cleaned_words = []
                for w in words:
                    clean_w = "".join(c for c in w if c.isalpha())
                    if clean_w:
                        cleaned_words.append(clean_w.capitalize())
                if cleaned_words:
                    return " ".join(cleaned_words)
        except Exception:
            pass

    if url_val and "facebook.com" in url_val.lower():
        url_lower = url_val.lower()
        try:
            segment = None
            if "/groups/" in url_lower:
                parts = url_val.split("facebook.com/groups/")
                if len(parts) > 1:
                    segment = parts[1].split("/")[0].split("?")[0].strip()
            elif "permalink.php" not in url_lower and "profile.php" not in url_lower:
                parts = url_val.split("facebook.com/")
                if len(parts) > 1:
                    segment = parts[1].split("/")[0].split("?")[0].strip()

            if segment and segment not in ["posts", "photos", "videos", "watch", "share", "groups", "pages", "events"]:
                split_camel = re.sub(r'(?<!^)(?=[A-Z])', ' ', segment)
                cleaned = split_camel.replace(".", " ").replace("-", " ").replace("_", " ")
                words = cleaned.split()
                cleaned_words = []
                for w in words:
                    clean_w = "".join(c for c in w if c.isalpha())
                    if clean_w:
                        cleaned_words.append(clean_w.capitalize())
                if cleaned_words:
                    return " ".join(cleaned_words)
        except Exception:
            pass

    return "Unknown"

router = APIRouter()

# Global dict to track in-memory background search task status (Requirement matching)
scraping_tasks = {}

# --- Pydantic Schemas ---
class SearchRequest(BaseModel):
    keyword: str
    timeframe: Optional[str] = "qdr:m3"
    limit: Optional[int] = 10
    platform: Optional[str] = "linkedin"
    match_type: Optional[str] = "partial"
    location: Optional[str] = None
    industry: Optional[str] = None
    search_type: Optional[str] = "sales"

class BulkDeleteRequest(BaseModel):
    urls: List[str]

class UpdateCRMRequest(BaseModel):
    sourceUrl: str
    crmStatus: str
    draftEmail: Optional[str] = ""
    authorName: Optional[str] = None
    companyName: Optional[str] = None
    buyingIntent: Optional[str] = None
    intentType: Optional[str] = None
    serviceRequired: Optional[str] = None
    industry: Optional[str] = None
    location: Optional[str] = None
    needDescription: Optional[str] = None
    contactInfo: Optional[str] = None
    platform: Optional[str] = None
    workPreference: Optional[str] = None
    skills: Optional[str] = None
    search_type: Optional[str] = None
    phone: Optional[str] = None
    rating: Optional[str] = None
    reviews: Optional[str] = None
    website: Optional[str] = None
    isConverted: Optional[bool] = None
    employeeCount: Optional[str] = None
    foundedYear: Optional[str] = None
    keyContacts: Optional[List[dict]] = None
    annualRevenue: Optional[str] = None
    totalFunding: Optional[str] = None
    keyContactsSource: Optional[str] = None

class GeneratePitchRequest(BaseModel):
    sourceUrl: str
    agencyName: Optional[str] = "Silvia Team"
    agencyInfo: Optional[str] = "premier design & development services"
    emailTone: Optional[str] = "Short & Conversational"

class EnrichContactRequest(BaseModel):
    authorName: Optional[str] = None
    companyName: Optional[str] = None
    sourceUrl: str

# --- Helper Functions ---
def determine_lead_platform(url: str) -> str:
    if not url:
        return "other"
    url_lower = url.lower()
    if "linkedin.com" in url_lower:
        return "linkedin"
    elif "facebook.com" in url_lower:
        return "facebook"
    elif "twitter.com" in url_lower or "x.com" in url_lower:
        return "twitter"
    elif "reddit.com" in url_lower:
        return "reddit"
    elif "google.com/maps" in url_lower or "places.googleapis.com" in url_lower:
        return "google_maps"
    elif "weworkremotely.com" in url_lower:
        return "weworkremotely"
    elif "freelancer.com" in url_lower:
        return "freelancer"
    elif "upwork.com" in url_lower:
        return "upwork"
    return "other"

def is_location_match(search_loc: str, lead_loc: str, text_context: str = None) -> bool:
    if not search_loc or is_empty_value(search_loc):
        return True
    s_clean = str(search_loc).lower().strip()
    if not lead_loc or is_empty_value(lead_loc):
        if text_context and s_clean in str(text_context).lower():
            return True
        return False
    l_clean = str(lead_loc).lower().strip()
    if s_clean in l_clean or l_clean in s_clean:
        return True
    abbreviations = {
        "uk": ["united kingdom", "u.k.", "england", "scotland", "wales", "ireland"],
        "us": ["united states", "usa", "u.s.a.", "u.s."],
        "usa": ["united states", "us", "u.s.a.", "u.s."],
        "uae": ["united arab emirates", "u.a.e.", "dubai", "abu dhabi"],
        "in": ["india"],
        "ca": ["canada"]
    }
    if s_clean in abbreviations:
        for alt in abbreviations[s_clean]:
            if alt in l_clean:
                return True
    countries = {
        "india", "united states", "united kingdom", "canada", "australia",
        "germany", "france", "uk", "us", "usa", "uae", "in", "ca"
    }
    if l_clean in countries:
        if text_context and s_clean in str(text_context).lower():
            return True
    return False

def extract_fallback_author(title: str, url: str) -> str:
    def normalize_link(l: str) -> str:
        if not l: return ""
        l_lower = l.lower().strip()
        for prefix in ["https://", "http://"]:
            if l_lower.startswith(prefix):
                l_lower = l_lower[len(prefix):]
        if "facebook.com" in l_lower:
            idx = l_lower.find("facebook.com")
            l_lower = l_lower[idx:]
        elif "linkedin.com" in l_lower:
            idx = l_lower.find("linkedin.com")
            l_lower = l_lower[idx:]
        return l_lower.strip("/")

    platform = determine_lead_platform(url)
    if title:
        if "on LinkedIn" in title:
            author = title.split("on LinkedIn")[0].strip()
            if author:
                validated = validate_author_name(author, platform)
                if validated and validated != "Unknown":
                    return validated
        for suffix in [" | Facebook", " - Facebook", " on Facebook"]:
            if suffix in title:
                author = title.split(suffix)[0].strip()
                if " - " in author:
                    author = author.split(" - ")[0].strip()
                if author:
                    validated = validate_author_name(author, platform)
                    if validated and validated != "Unknown":
                        return validated
        for suffix in [" on X", " | Twitter", " - Twitter", " / X"]:
            if suffix in title:
                author = title.split(suffix)[0].strip()
                if "(" in author and "@" in author:
                    author = author.split("(")[0].strip()
                if author:
                    validated = validate_author_name(author, platform)
                    if validated and validated != "Unknown":
                        return validated
        for suffix in [" : reddit", " | reddit", " - reddit", " on reddit"]:
            if suffix in title:
                author = title.split(suffix)[0].strip()
                if author:
                    validated = validate_author_name(author, platform)
                    if validated and validated != "Unknown":
                        return validated

    username = ""
    if "linkedin.com/posts/" in url:
        try:
            part = url.split("linkedin.com/posts/")[1]
            part = part.split("?")[0].strip("/")
            if "_" in part:
                username = part.split("_")[0]
            elif "-activity-" in part:
                username = part.split("-activity-")[0]
            elif "_activity-" in part:
                username = part.split("_activity-")[0]
            else:
                username = part
        except Exception:
            pass
    elif "linkedin.com/in/" in url:
        try:
            part = url.split("linkedin.com/in/")[1]
            username = part.split("/")[0].split("?")[0]
        except Exception:
            pass

    if username:
        username_clean = username.replace("-", " ").replace(".", " ")
        words = username_clean.split()
        cleaned_words = []
        for w in words:
            if not w.isdigit():
                cleaned_words.append(w.capitalize())
        if cleaned_words:
            return " ".join(cleaned_words)

    # Facebook profile lookup fallback segment
    fb_username = ""
    if url and "facebook.com" in url.lower():
        url_lower = url.lower()
        try:
            if "/groups/" in url_lower:
                idx = url_lower.find("facebook.com/groups/")
                if idx != -1:
                    part_after = url[idx + len("facebook.com/groups/"):]
                    fb_username = part_after.split("/")[0].split("?")[0].strip()
            elif "permalink.php" not in url_lower:
                idx = url_lower.find("facebook.com/")
                if idx != -1:
                    part_after = url[idx + len("facebook.com/"):]
                    segment = part_after.split("/")[0].split("?")[0].strip()
                    if segment and segment not in ["posts", "photos", "videos", "watch", "share", "groups", "pages", "events"]:
                        fb_username = segment
        except Exception:
            pass

    if fb_username and not fb_username.isdigit():
        split_camel = re.sub(r'(?<!^)(?=[A-Z])', ' ', fb_username)
        username_clean = split_camel.replace("-", " ").replace(".", " ").replace("_", " ")
        words = username_clean.split()
        cleaned_words = []
        for w in words:
            clean_w = "".join(c for c in w if c.isalpha())
            if clean_w:
                cleaned_words.append(clean_w.capitalize())
        if cleaned_words:
            return " ".join(cleaned_words)

    return "Unknown"

def fetch_title_from_url(url: str) -> str:
    # Serper search fallback to fetch page title if not crawlable directly
    try:
        from app.services.serper import search_leads
        results = search_leads(url, tbs="")
        if results:
            return results[0].get("title", "")
    except Exception as e:
        print(f"Error fetching title from url {url}: {e}")
    return ""

def enrich_profile_details(author: str, url: str = None) -> dict:
    return {} # Simple fallback placeholder for profile enrichment if apis are missing

# --- DB Adapter Wrappers ---
def load_db(user_id: str) -> dict:
    coll = db_manager.get_collection("leads")
    if coll is not None:
        db_leads = list(coll.find({"userId": user_id}))
        for lead in db_leads:
            if "_id" in lead:
                lead["_id"] = str(lead["_id"])
    else:
        db_leads = db_manager.json_db.find("leads", {"userId": user_id})
    return {lead.get("sourceUrl"): lead for lead in db_leads if lead.get("sourceUrl")}

def save_db(db_data: dict, user_id: str):
    coll = db_manager.get_collection("leads")
    for url, lead in db_data.items():
        lead_copy = dict(lead)
        if "_id" in lead_copy:
            from bson import ObjectId
            try:
                lead_copy["_id"] = ObjectId(lead_copy["_id"])
            except Exception:
                del lead_copy["_id"]
        lead_copy["sourceUrl"] = url
        lead_copy["userId"] = user_id
        if "id" not in lead_copy or not lead_copy["id"]:
            lead_copy["id"] = f"lead_{uuid.uuid4().hex[:12]}"
        # Also store crmStatus mapping to stage for pipeline compatibility
        crm_stage_map = {
            "New": "Discovered",
            "New Discovery": "Discovered",
            "Drafted": "Pitch Drafted",
            "Emailed": "Emailed",
            "Replied": "Responded",
            "Disqualified": "Disqualified"
        }
        lead_copy["stage"] = crm_stage_map.get(lead_copy.get("crmStatus", "New"), "Discovered")
        
        if coll is not None:
            coll.replace_one({"sourceUrl": url, "userId": user_id}, lead_copy, upsert=True)
        else:
            existing = db_manager.json_db.find_one("leads", {"sourceUrl": url, "userId": user_id})
            if existing:
                db_manager.json_db.update_one("leads", {"sourceUrl": url, "userId": user_id}, {"$set": lead_copy})
            else:
                db_manager.json_db.insert_one("leads", lead_copy)

def load_searches(user_id: str) -> list:
    coll = db_manager.get_collection("searches")
    if coll is not None:
        searches = list(coll.find({"userId": user_id}))
        for s in searches:
            if "_id" in s:
                s["_id"] = str(s["_id"])
        return searches
    else:
        return db_manager.json_db.find("searches", {"userId": user_id})

def save_searches(searches: list, user_id: str):
    coll = db_manager.get_collection("searches")
    for s in searches:
        s_copy = dict(s)
        if "_id" in s_copy:
            from bson import ObjectId
            try:
                s_copy["_id"] = ObjectId(s_copy["_id"])
            except Exception:
                del s_copy["_id"]
        s_copy["userId"] = user_id
        if coll is not None:
            coll.replace_one(
                {
                    "keyword": s_copy.get("keyword"),
                    "platform": s_copy.get("platform"),
                    "search_type": s_copy.get("search_type", "sales"),
                    "userId": user_id
                },
                s_copy,
                upsert=True
            )
        else:
            existing = db_manager.json_db.find_one("searches", {
                "keyword": s_copy.get("keyword"),
                "platform": s_copy.get("platform"),
                "search_type": s_copy.get("search_type", "sales"),
                "userId": user_id
            })
            if existing:
                db_manager.json_db.update_one("searches", {
                    "keyword": s_copy.get("keyword"),
                    "platform": s_copy.get("platform"),
                    "search_type": s_copy.get("search_type", "sales"),
                    "userId": user_id
                }, {"$set": s_copy})
            else:
                db_manager.json_db.insert_one("searches", s_copy)

def delete_lead_from_db(source_url: str, user_id: str) -> bool:
    coll = db_manager.get_collection("leads")
    if coll is not None:
        res = coll.delete_one({"sourceUrl": source_url, "userId": user_id})
        return res.deleted_count > 0
    else:
        return db_manager.json_db.delete_one("leads", {"sourceUrl": source_url, "userId": user_id})

def delete_search_from_db(search_id: str, user_id: str) -> bool:
    coll = db_manager.get_collection("searches")
    if coll is not None:
        # Check if ID matches string or object match
        res = coll.delete_one({"id": search_id, "userId": user_id})
        return res.deleted_count > 0
    else:
        return db_manager.json_db.delete_one("searches", {"id": search_id, "userId": user_id})

# --- Background Worker ---
async def perform_search_background(task_id: str, payload: SearchRequest, user_id: str):
    try:
        platform = (payload.platform or "linkedin").lower().strip()
        timeframe = payload.timeframe or "qdr:m3"
        
        # 1. Generate intent queries
        if platform in ["google_maps", "weworkremotely", "freelancer", "upwork"]:
            intent_queries = [payload.keyword]
        else:
            intent_queries = IntentQueryGenerator.generate(payload.keyword)
        print(f"\n[Search] Generating intent-based search terms: {intent_queries}")
        
        # 2. Collect and search across adapters
        raw_results = []
        if platform == "all":
            platforms = ["linkedin", "facebook", "twitter"]
        else:
            platforms = [platform]
            
        db = load_db(user_id)
        
        for plat in platforms:
            adapter = get_adapter(plat)
            for q in intent_queries:
                try:
                    if plat == "google_maps":
                        places_key = settings.GOOGLE_PLACES_API_KEY
                        
                        # Extract exclusion sets to skip duplicate scraping
                        exclude_urls = set()
                        exclude_names = set()
                        for lead in db.values():
                            if lead.get("platform") == "google_maps":
                                url = lead.get("sourceUrl")
                                name = lead.get("companyName")
                                if url:
                                    exclude_urls.add(url.strip())
                                if name:
                                    exclude_names.add(name.lower().strip())
                                    
                        res = await asyncio.to_thread(
                            adapter.search,
                            q,
                            timeframe=timeframe,
                            match_type=payload.match_type or "partial",
                            location=payload.location,
                            industry=payload.industry,
                            api_key=places_key,
                            limit=payload.limit or 10,
                            exclude_urls=exclude_urls,
                            exclude_names=exclude_names
                        )
                    else:
                        serper_key = settings.SERPER_API_KEY
                        res = await asyncio.to_thread(
                            adapter.search,
                            q,
                            timeframe=timeframe,
                            match_type=payload.match_type or "partial",
                            location=payload.location,
                            industry=payload.industry,
                            api_key=serper_key,
                            limit=payload.limit or 10,
                            raw_keyword=payload.keyword
                        )
                    if res:
                        raw_results.extend(res)
                except Exception as e:
                    print(f"[Search] Error searching query '{q}' on platform '{plat}': {e}")
                    
        # 3. De-duplicate raw results by link
        seen_urls = set()
        unique_raw_results = []
        for r in raw_results:
            url = r.get("link")
            if url and url not in seen_urls:
                seen_urls.add(url)
                unique_raw_results.append(r)
                
        total_results_found = len(unique_raw_results)
        print(f"[Search] Merged results: {total_results_found} unique posts/threads found.")
        
        user_coll = db_manager.get_collection("users")
        user_profile = None
        if user_coll is not None:
            user_profile = user_coll.find_one({"id": user_id})
        else:
            user_profile = db_manager.json_db.find_one("users", {"id": user_id})

        current_search_leads = []
        sem = asyncio.Semaphore(3)
        
        async def process_one(result):
            async with sem:
                title = result.get("title", "")
                snippet = result.get("snippet", "")
                source_url = result.get("link", "")
                if not source_url:
                    return None
                try:
                    # Determine platform first
                    plat_resolved = determine_lead_platform(source_url)
                    
                    # 4. Intent Signal Classification
                    new_lead_data = await asyncio.to_thread(classify_lead_intent, title, snippet, payload.search_type or "sales", plat_resolved)
                    
                    # Merge with existing lead to preserve _id and createdAt
                    if source_url in db:
                        lead = dict(db[source_url])
                        for k, v in new_lead_data.items():
                            if v is not None:
                                lead[k] = v
                    else:
                        lead = new_lead_data
                        lead["createdAt"] = datetime.datetime.utcnow().isoformat()
                        
                    lead["sourceUrl"] = source_url
                    lead["platform"] = plat_resolved
                    lead["search_type"] = payload.search_type or "sales"
                    lead["isConverted"] = False
                    
                    # Initialize candidate-specific fields
                    if "workPreference" not in lead:
                        lead["workPreference"] = "Unknown"
                    if "skills" not in lead:
                        lead["skills"] = ""
                    if "experienceLevel" not in lead:
                        lead["experienceLevel"] = "Unknown"
                    
                    # Overrides for Google Maps leads
                    if lead.get("platform") == "google_maps":
                        lead["companyName"] = result.get("meta_business_name", "Unknown Business")
                        lead["location"] = result.get("meta_address", "Not Specified")
                        lead["phone"] = result.get("phone", "")
                        lead["rating"] = result.get("rating", "")
                        lead["reviews"] = result.get("reviews", "")
                        lead["website"] = result.get("meta_website", "")
                        lead["linkedin"] = result.get("meta_linkedin", "")
                        lead["foundedYear"] = result.get("meta_founded_year", "")
                        if result.get("meta_description"):
                            lead["needDescription"] = result.get("meta_description")
                        if result.get("meta_owner_name"):
                            lead["authorName"] = result.get("meta_owner_name")
                        lead["keyContacts"] = []
                    
                    # 5. Lead Intent Scoring Engine
                    lead = calculate_lead_score(lead, user_profile)
                    
                    # Ensure author name is populated (use fallback parser if missing)
                    author = lead.get("authorName")
                    if is_empty_value(author):
                        if lead.get("platform") == "google_maps":
                            author = "Business Owner"
                        else:
                            author = await asyncio.to_thread(extract_fallback_author, title, source_url)
                    
                    # Apply author name validation
                    author = validate_author_name(author, lead.get("platform"))
                    lead["authorName"] = author
                    
                    # Apply company name validation (bypass sentence validation filters for Google Maps leads)
                    if lead.get("platform") == "google_maps":
                        company = lead.get("companyName")
                    else:
                        company = validate_company_name(lead.get("companyName"))
                    lead["companyName"] = company
                    
                    # Secondary Enrichment search if company details or location are missing
                    if lead.get("platform") != "google_maps" and not is_empty_value(author):
                        if is_empty_value(lead.get("companyName")) or is_empty_value(lead.get("location")) or (payload.location and payload.location.strip()):
                            enriched_data = await asyncio.to_thread(enrich_profile_details, author, source_url)
                            if enriched_data:
                                ec = enriched_data.get("companyName")
                                ei = enriched_data.get("industry")
                                el = enriched_data.get("location")
                                if not is_empty_value(ec) and is_empty_value(lead.get("companyName")):
                                    lead["companyName"] = validate_company_name(ec)
                                if not is_empty_value(ei) and is_empty_value(lead.get("industry")):
                                    lead["industry"] = ei
                                if not is_empty_value(el):
                                    lead["location"] = el
       
                    # 6. Contact Enrichment / Email Guessing
                    if lead.get("platform") == "google_maps":
                        c_info = result.get("meta_contact_info")
                        if not c_info:
                            email_matches = re.findall(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,6}", f"{title} {snippet}")
                            if email_matches:
                                c_info = email_matches[0]
                        lead["contactInfo"] = c_info
                        lead["contactSource"] = "google_maps_crawl" if c_info else "none"
                        lead["contactConfidence"] = "high" if c_info else "none"
                    else:
                        lead["contactInfo"] = None
                        lead["contactSource"] = "none"
                        lead["contactConfidence"] = "none"
                    
                    # Enforce location filtering if specified (skip for Google Maps as it's already location-scoped)
                    if lead.get("platform") != "google_maps" and payload.location and payload.location.strip():
                        lead_loc = lead.get("location")
                        if not is_location_match(payload.location, lead_loc, text_context=f"{title} {snippet}"):
                            return None
                    
                    return {"status": "success", "lead": lead, "source_url": source_url}
                except Exception as err:
                    print(f"Error classifying lead {title}: {err}")
                    fallback_author = await asyncio.to_thread(extract_fallback_author, title, source_url)
                    fallback_author = validate_author_name(fallback_author, determine_lead_platform(source_url))
                    fallback_lead = {
                        "authorName": fallback_author,
                        "companyName": "Not Specified",
                        "buyingIntent": "Unknown",
                        "intentType": "General Discussion",
                        "serviceRequired": "Unknown",
                        "industry": "Unknown",
                        "location": "Unknown",
                        "needDescription": snippet[:100] + "...",
                        "contactInfo": None,
                        "contactSource": "guessed",
                        "contactConfidence": "low",
                        "confidenceScore": 0,
                        "leadScore": 10,
                        "leadCategory": "Low Intent",
                        "leadStatus": "Unqualified",
                        "sourceUrl": source_url,
                        "crmStatus": "New",
                        "draftEmail": "",
                        "platform": determine_lead_platform(source_url),
                        "search_type": payload.search_type or "sales",
                        "workPreference": "Unknown",
                        "skills": "",
                        "experienceLevel": "Unknown",
                        "createdAt": datetime.datetime.utcnow().isoformat(),
                        "isConverted": False
                    }
                    
                    if fallback_lead.get("platform") == "google_maps":
                        fallback_lead["companyName"] = result.get("meta_business_name", "Unknown Business")
                        fallback_lead["location"] = result.get("meta_address", "Not Specified")
                        fallback_lead["phone"] = result.get("phone", "")
                        fallback_lead["rating"] = result.get("rating", "")
                        fallback_lead["reviews"] = result.get("reviews", "")
                        fallback_lead["website"] = result.get("meta_website", "")
                        fallback_lead["linkedin"] = result.get("meta_linkedin", "")
                    
                    if fallback_lead.get("platform") != "google_maps" and payload.location and payload.location.strip():
                        lead_loc = fallback_lead.get("location")
                        if not is_location_match(payload.location, lead_loc, text_context=f"{title} {snippet}"):
                            return None
                    
                    return {"status": "fallback", "lead": fallback_lead, "source_url": source_url}

        # Parallelize AI calls
        processed_results = await asyncio.gather(*[process_one(r) for r in unique_raw_results[:payload.limit]])
        
        processed_count = 0
        qualified_count = 0
        for res in processed_results:
            if not res:
                continue
            lead = res["lead"]
            source_url = res["source_url"]
            processed_count += 1
            
            # Preserve CRM stages & draft emails if they exist
            lead["crmStatus"] = db[source_url].get("crmStatus", "New") if source_url in db else "New"
            lead["draftEmail"] = db[source_url].get("draftEmail", "") if source_url in db else ""
            
            # Duplicate checking and save in db dict
            db[source_url] = lead
            if lead.get("leadCategory") in ["High Intent", "Medium Intent"]:
                qualified_count += 1
            current_search_leads.append(lead)

        # Save leads database
        save_db(db, user_id)

        # Calculate qualification rate
        rate = int((qualified_count / processed_count) * 100) if processed_count > 0 else 0

        # Save search metrics
        searches = load_searches(user_id)
        existing_search = next((s for s in searches if s.get("keyword") == payload.keyword and s.get("platform", "linkedin") == platform and s.get("location") == payload.location and s.get("industry") == payload.industry), None)
        if existing_search:
            searches.remove(existing_search)
        
        new_search_doc = {
            "id": existing_search.get("id") if existing_search else f"search_{int(time.time())}_{uuid.uuid4().hex[:6]}",
            "keyword": payload.keyword,
            "platform": platform,
            "search_type": payload.search_type or "sales",
            "timestamp": datetime.datetime.now().isoformat(),
            "timeframe": timeframe,
            "limit": payload.limit,
            "matchType": payload.match_type or "partial",
            "location": payload.location,
            "industry": payload.industry,
            "resultsFound": total_results_found,
            "qualifiedLeadsCount": qualified_count,
            "qualificationRate": rate,
            "leadUrls": list(set((existing_search.get("leadUrls", []) if existing_search else []) + [l.get("sourceUrl") for l in current_search_leads if l.get("sourceUrl")]))
        }
        searches.insert(0, new_search_doc)
        save_searches(searches, user_id)
        
        # Deduct SaaS credits from user balance for the performed search (1 credit per lead scraped for demo)
        credits_cost = len(current_search_leads)
        success, msg, info = CreditService.check_and_deduct(
            user_id,
            f"Scraper search: {payload.keyword} ({platform}) - {credits_cost} leads",
            credits_cost
        )
        if not success:
            raise Exception(msg)

        # Update background task global dict to success status
        scraping_tasks[task_id] = {
            "status": "completed",
            "result": current_search_leads,
            "error": None,
            "keyword": payload.keyword,
            "platform": platform
        }
    except Exception as exc:
        print(f"[Search Background Worker] Fatal crash: {exc}")
        scraping_tasks[task_id] = {
            "status": "failed",
            "result": None,
            "error": str(exc),
            "keyword": payload.keyword,
            "platform": payload.platform
        }

# --- Legacy Compatibility API Endpoints ---
@router.post("/api/search")
async def run_search(payload: SearchRequest, background_tasks: BackgroundTasks, user_id: str = Depends(get_current_user_id)):
    if not payload.keyword.strip():
        raise HTTPException(status_code=400, detail="Keyword is required")
    
    # Pre-check credits balance
    credits_cost = settings.COST_MAP_SEARCH if (payload.platform or "linkedin").lower().strip() == "google_maps" else 1
    credits_info = CreditService.get_user_credits(user_id)
    if credits_info.get("creditsRemaining", 0) < credits_cost:
        raise HTTPException(status_code=400, detail=f"Insufficient credits. Requires {credits_cost} credit(s). Please upgrade your plan.")
    
    # Generate unique task ID
    task_id = f"task_{int(time.time())}_{uuid.uuid4().hex[:8]}"
    
    # Enforce standard cleanup of in-memory tasks list
    if len(scraping_tasks) > 100:
        sorted_keys = sorted(scraping_tasks.keys())
        for k in sorted_keys[:-100]:
            scraping_tasks.pop(k, None)
            
    scraping_tasks[task_id] = {
        "status": "running",
        "result": None,
        "error": None,
        "keyword": payload.keyword,
        "platform": payload.platform
    }
    
    background_tasks.add_task(perform_search_background, task_id, payload, user_id)
    return {
        "status": "pending",
        "task_id": task_id
    }

@router.get("/api/search/status/{task_id}")
async def get_search_status(task_id: str, user_id: str = Depends(get_current_user_id)):
    task = scraping_tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Search task not found")
    return task

@router.get("/api/searches")
async def get_searches_list(user_id: str = Depends(get_current_user_id)):
    searches = load_searches(user_id)
    return {"searches": searches}

@router.delete("/api/searches/{search_id}")
async def delete_search_record(search_id: str, user_id: str = Depends(get_current_user_id)):
    if search_id == "all":
        raise HTTPException(status_code=400, detail="Cannot delete default database view")
    success = delete_search_from_db(search_id, user_id)
    if success:
        return {"status": "success", "message": "Search query deleted successfully"}
    else:
        raise HTTPException(status_code=404, detail="Search query not found")

@router.get("/api/leads")
async def get_current_leads_endpoint(user_id: str = Depends(get_current_user_id)):
    db = load_db(user_id)
    leads_list = list(db.values())
    return {"leads": leads_list, "count": len(leads_list)}

@router.post("/api/leads/update")
async def update_lead_crm_endpoint(payload: UpdateCRMRequest, user_id: str = Depends(get_current_user_id)):
    db = load_db(user_id)
    if payload.sourceUrl not in db:
        # Initialize a new lead if not present (converted tender or external scan)
        db[payload.sourceUrl] = {
            "sourceUrl": payload.sourceUrl,
            "crmStatus": payload.crmStatus,
            "draftEmail": payload.draftEmail or "",
            "createdAt": datetime.datetime.utcnow().isoformat(),
            "platform": payload.platform or determine_lead_platform(payload.sourceUrl),
            "isConverted": payload.isConverted if payload.isConverted is not None else True
        }
        
    db[payload.sourceUrl]["crmStatus"] = payload.crmStatus
    db[payload.sourceUrl]["draftEmail"] = payload.draftEmail
    
    if payload.isConverted is not None:
        db[payload.sourceUrl]["isConverted"] = payload.isConverted
    if payload.companyName is not None:
        db[payload.sourceUrl]["companyName"] = payload.companyName
    if payload.buyingIntent is not None:
        db[payload.sourceUrl]["buyingIntent"] = payload.buyingIntent
    if payload.intentType is not None:
        db[payload.sourceUrl]["intentType"] = payload.intentType
    if payload.serviceRequired is not None:
        db[payload.sourceUrl]["serviceRequired"] = payload.serviceRequired
    if payload.industry is not None:
        db[payload.sourceUrl]["industry"] = payload.industry
    if payload.location is not None:
        db[payload.sourceUrl]["location"] = payload.location
    if payload.needDescription is not None:
        db[payload.sourceUrl]["needDescription"] = payload.needDescription
    if payload.contactInfo is not None:
        db[payload.sourceUrl]["contactInfo"] = payload.contactInfo
        
        # Auto-update authorName if email is provided and current authorName is Unknown/fallback
        if not is_empty_value(payload.contactInfo):
            current_author = db[payload.sourceUrl].get("authorName")
            lead_plat = db[payload.sourceUrl].get("platform")
            if is_empty_value(current_author) or (lead_plat == "facebook" and is_facebook_fallback_name(current_author, payload.sourceUrl)):
                email_author = extract_author_from_email_or_url(payload.contactInfo, payload.sourceUrl)
                if email_author and email_author != "Unknown":
                    validated_email_author = validate_author_name(email_author, lead_plat)
                    if validated_email_author and validated_email_author != "Unknown":
                        db[payload.sourceUrl]["authorName"] = validated_email_author
 
    if payload.authorName is not None:
        db[payload.sourceUrl]["authorName"] = payload.authorName
    if payload.platform is not None:
        db[payload.sourceUrl]["platform"] = payload.platform
    if payload.workPreference is not None:
        db[payload.sourceUrl]["workPreference"] = payload.workPreference
    if payload.skills is not None:
        db[payload.sourceUrl]["skills"] = payload.skills
    if payload.search_type is not None:
        db[payload.sourceUrl]["search_type"] = payload.search_type
    if payload.phone is not None:
        db[payload.sourceUrl]["phone"] = payload.phone
    if payload.rating is not None:
        db[payload.sourceUrl]["rating"] = payload.rating
    if payload.reviews is not None:
        db[payload.sourceUrl]["reviews"] = payload.reviews
    if payload.website is not None:
        db[payload.sourceUrl]["website"] = payload.website
    if payload.employeeCount is not None:
        db[payload.sourceUrl]["employeeCount"] = payload.employeeCount
    if payload.foundedYear is not None:
        db[payload.sourceUrl]["foundedYear"] = payload.foundedYear
    if payload.keyContacts is not None:
        db[payload.sourceUrl]["keyContacts"] = payload.keyContacts
    if payload.annualRevenue is not None:
        db[payload.sourceUrl]["annualRevenue"] = payload.annualRevenue
    if payload.totalFunding is not None:
        db[payload.sourceUrl]["totalFunding"] = payload.totalFunding
    if payload.keyContactsSource is not None:
        db[payload.sourceUrl]["keyContactsSource"] = payload.keyContactsSource
        
    # Recalculate score after user modifications
    user_coll = db_manager.get_collection("users")
    user_profile = None
    if user_coll is not None:
        user_profile = user_coll.find_one({"id": user_id})
    else:
        user_profile = db_manager.json_db.find_one("users", {"id": user_id})

    db[payload.sourceUrl] = calculate_lead_score(db[payload.sourceUrl], user_profile)
    save_db(db, user_id)
    return {"status": "success", "lead": db[payload.sourceUrl]}

@router.post("/api/leads/bulk-delete")
async def bulk_delete_leads_endpoint(payload: BulkDeleteRequest, user_id: str = Depends(get_current_user_id)):
    success_count = 0
    for url in payload.urls:
        if delete_lead_from_db(url, user_id):
            success_count += 1
    return {"status": "success", "message": f"Successfully deleted {success_count} leads"}

@router.post("/api/enrich-contact")
async def enrich_lead_contact_endpoint(payload: EnrichContactRequest, user_id: str = Depends(get_current_user_id)):
    db = load_db(user_id)
    if payload.sourceUrl not in db:
        raise HTTPException(status_code=404, detail="Lead not found")
        
    lead = db[payload.sourceUrl]

    # Deduct SaaS credits from user balance for the email reveal (Commented out for demo)
    # success, msg, info = CreditService.check_and_deduct(
    #     user_id,
    #     f"Email Enrichment: {lead.get('authorName', 'Lead')}",
    #     settings.COST_REVEAL_EMAIL
    # )
    # if not success:
    #     raise HTTPException(status_code=400, detail=msg)

    # Check cache/smart reuse (other users' database copies)
    try:
        coll = db_manager.get_collection("leads")
        if coll is not None:
            existing_enrichment = coll.find_one({
                "sourceUrl": payload.sourceUrl,
                "contactInfo": {"$exists": True, "$ne": "", "$nin": [None, "None", "not specified", "Unknown"]},
                "contactSource": {"$in": ["apollo", "hunter", "prospeo", "serper"]}
            })
            if existing_enrichment:
                lead["contactInfo"] = existing_enrichment["contactInfo"]
                lead["contactSource"] = existing_enrichment.get("contactSource", "none")
                lead["contactConfidence"] = existing_enrichment.get("contactConfidence", "none")
                if existing_enrichment.get("authorName") and is_empty_value(lead.get("authorName")):
                    lead["authorName"] = existing_enrichment["authorName"]
                if existing_enrichment.get("companyName") and is_empty_value(lead.get("companyName")):
                    lead["companyName"] = existing_enrichment["companyName"]
                if existing_enrichment.get("location") and is_empty_value(lead.get("location")):
                    lead["location"] = existing_enrichment["location"]
                if existing_enrichment.get("industry") and is_empty_value(lead.get("industry")):
                    lead["industry"] = existing_enrichment["industry"]
                    
                db[payload.sourceUrl] = lead
                save_db(db, user_id)
                return {
                    "status": "success", 
                    "contactInfo": lead.get("contactInfo"),
                    "contactSource": lead.get("contactSource", "none"),
                    "contactConfidence": lead.get("contactConfidence", "none"),
                    "authorName": lead.get("authorName"),
                    "companyName": lead.get("companyName"),
                    "industry": lead.get("industry"),
                    "location": lead.get("location"),
                    "keyContactsSource": lead.get("keyContactsSource", "none")
                }
    except Exception as e:
        print(f"[Enrich Contact Cache] Error querying existing enrichment: {e}")

    # 1. Determine who we are enriching
    enriching_key_contact = False
    target_author = lead.get("authorName")
    
    if payload.authorName and str(payload.authorName).strip():
        # If payload.authorName is provided, we use it
        target_author = payload.authorName
        # Check if this name is in keyContacts
        key_contacts = lead.get("keyContacts") or []
        for contact in key_contacts:
            if contact.get("name") and contact.get("name").strip().lower() == target_author.strip().lower():
                enriching_key_contact = True
                break
    else:
        # Fallback to lead authorName logic as before
        if is_empty_value(target_author):
            title = fetch_title_from_url(payload.sourceUrl)
            target_author = extract_fallback_author(title, payload.sourceUrl)
            target_author = validate_author_name(target_author, lead.get("platform"))
            lead["authorName"] = target_author
            
        is_generic_author = is_empty_value(target_author) or str(target_author).strip().lower() in ["business owner", "unknown", "unknown poster", "lead", "job enquiry", "hr", "hiring", "contact", "support"]
        if is_generic_author:
            key_contacts = lead.get("keyContacts") or []
            if key_contacts:
                selected_contact = None
                for c in key_contacts:
                    title_lower = str(c.get("title", "")).lower()
                    if any(kw in title_lower for kw in ["ceo", "founder", "owner", "director", "president", "partner", "manager"]):
                        selected_contact = c
                        break
                if not selected_contact:
                    selected_contact = key_contacts[0]
                if selected_contact.get("name"):
                    target_author = selected_contact["name"]
                    print(f"[Enrich Contact Cache] generic author overridden with key contact: {target_author}")
                    
    company = payload.companyName or lead.get("companyName")
    
    if not is_empty_value(target_author) and is_empty_value(company):
        enriched = enrich_profile_details(target_author, payload.sourceUrl)
        if enriched:
            ec = enriched.get("companyName")
            ei = enriched.get("industry")
            el = enriched.get("location")
            if not is_empty_value(ec):
                lead["companyName"] = ec
                company = ec
            if not is_empty_value(ei):
                lead["industry"] = ei
            if not is_empty_value(el):
                lead["location"] = el

    # Run modular enrichment manager
    enrich_mgr = ContactEnrichmentManager()
    enrichment_info = enrich_mgr.enrich(target_author, company)
    
    c_info = enrichment_info.get("email")
    if c_info == "hello@company.com" or is_empty_value(c_info):
        c_info = None
        
    # Update the lead in DB based on whether it is a key contact or the main contact
    if enriching_key_contact:
        key_contacts = lead.get("keyContacts") or []
        updated = False
        from app.enrichment.contact_enrichment import find_linkedin_profile
        for contact in key_contacts:
            if contact.get("name") and contact.get("name").strip().lower() == target_author.strip().lower():
                contact["email"] = c_info or "No Email Found"
                if enrichment_info.get("contactSource"):
                    contact["source"] = enrichment_info.get("contactSource")
                # Also resolve LinkedIn URL if missing
                if not contact.get("linkedin") or str(contact.get("linkedin")).strip().lower() in ["none", "null", "undefined", "no linkedin link"]:
                    contact["linkedin"] = find_linkedin_profile(target_author, company, lead.get("linkedin"))
                updated = True
        if updated:
            lead["keyContacts"] = key_contacts
    else:
        # This is for the primary contact
        if c_info and not is_empty_value(c_info):
            lead["contactInfo"] = c_info
            lead["contactSource"] = enrichment_info.get("contactSource")
            lead["contactConfidence"] = enrichment_info.get("contactConfidence")
            # Save B2B enriched author name
            if target_author and str(target_author).strip().lower() not in ["business owner", "unknown", "unknown poster", "lead", "job enquiry", "hr", "hiring", "contact", "support"]:
                lead["authorName"] = target_author
                
    if is_empty_value(lead.get("companyName")) and enrichment_info.get("companyName"):
        lead["companyName"] = validate_company_name(enrichment_info.get("companyName"))
        
    if enrichment_info.get("authorName") and not enriching_key_contact:
        curr_author = lead.get("authorName")
        if is_empty_value(curr_author) or str(curr_author).strip().lower() in ["business owner", "unknown", "unknown poster", "lead", "job enquiry", "hr", "hiring", "contact", "support"]:
            lead["authorName"] = enrichment_info["authorName"]
            
    if not is_empty_value(c_info) and not enriching_key_contact:
        current_author = lead.get("authorName")
        if is_empty_value(current_author) or (lead.get("platform") == "facebook" and is_facebook_fallback_name(current_author, payload.sourceUrl)):
            email_author = extract_author_from_email_or_url(c_info, payload.sourceUrl)
            if email_author and email_author != "Unknown":
                validated_email_author = validate_author_name(email_author, lead.get("platform"))
                if validated_email_author and validated_email_author != "Unknown":
                    lead["authorName"] = validated_email_author
    
    db[payload.sourceUrl] = lead
    save_db(db, user_id)
    return {
        "status": "success", 
        "contactInfo": lead.get("contactInfo"),
        "contactSource": lead.get("contactSource", "none"),
        "contactConfidence": lead.get("contactConfidence", "none"),
        "authorName": lead.get("authorName"),
        "companyName": lead.get("companyName"),
        "industry": lead.get("industry"),
        "location": lead.get("location"),
        "keyContacts": lead.get("keyContacts", []),
        "keyContactsSource": lead.get("keyContactsSource", "none")
    }

@router.post("/api/enrich-team")
async def enrich_lead_team_endpoint(payload: EnrichContactRequest, user_id: str = Depends(get_current_user_id)):
    db = load_db(user_id)
    if payload.sourceUrl not in db:
        raise HTTPException(status_code=404, detail="Lead not found")
        
    lead = db[payload.sourceUrl]

    # Deduct SaaS credits from user balance for the email reveal (Commented out for demo)
    # success, msg, info = CreditService.check_and_deduct(
    #     user_id,
    #     f"Team Enrichment: {lead.get('companyName', 'Company')}",
    #     settings.COST_REVEAL_EMAIL
    # )
    # if not success:
    #     raise HTTPException(status_code=400, detail=msg)

    # Check cache/smart reuse (other users' database copies)
    try:
        coll = db_manager.get_collection("leads")
        if coll is not None:
            existing_enrichment = coll.find_one({
                "sourceUrl": payload.sourceUrl,
                "keyContacts": {"$exists": True, "$not": {"$size": 0}},
                "keyContactsSource": {"$in": ["apollo", "serper", "hunter", "prospeo"]}
            })
            if existing_enrichment:
                lead["keyContacts"] = existing_enrichment.get("keyContacts", [])
                lead["keyContactsSource"] = existing_enrichment.get("keyContactsSource", "none")
                if existing_enrichment.get("employeeCount"):
                    lead["employeeCount"] = existing_enrichment["employeeCount"]
                if existing_enrichment.get("foundedYear"):
                    lead["foundedYear"] = existing_enrichment["foundedYear"]
                if existing_enrichment.get("annualRevenue"):
                    lead["annualRevenue"] = existing_enrichment["annualRevenue"]
                if existing_enrichment.get("totalFunding"):
                    lead["totalFunding"] = existing_enrichment["totalFunding"]
                if existing_enrichment.get("industry") and is_empty_value(lead.get("industry")):
                    lead["industry"] = existing_enrichment["industry"]
                    
                db[payload.sourceUrl] = lead
                save_db(db, user_id)
                return {
                    "status": "success",
                    "companyName": lead.get("companyName"),
                    "industry": lead.get("industry"),
                    "location": lead.get("location"),
                    "employeeCount": lead.get("employeeCount"),
                    "foundedYear": lead.get("foundedYear"),
                    "annualRevenue": lead.get("annualRevenue"),
                    "totalFunding": lead.get("totalFunding"),
                    "keyContacts": lead.get("keyContacts", []),
                    "keyContactsSource": lead.get("keyContactsSource", "none")
                }
    except Exception as e:
        print(f"[Enrich Team Cache] Error querying existing enrichment: {e}")

    author = lead.get("authorName")
    company = lead.get("companyName")
    company_linkedin = lead.get("linkedin")
    
    # Run modular enrichment manager
    enrich_mgr = ContactEnrichmentManager()
    enrichment_info = enrich_mgr.enrich_team(author, company, company_linkedin=company_linkedin)
    
    if enrichment_info.get("employeeCount"):
        lead["employeeCount"] = str(enrichment_info["employeeCount"])
    if enrichment_info.get("foundedYear"):
        lead["foundedYear"] = str(enrichment_info["foundedYear"])
    if enrichment_info.get("annualRevenue"):
        lead["annualRevenue"] = str(enrichment_info["annualRevenue"])
    if enrichment_info.get("totalFunding"):
        lead["totalFunding"] = str(enrichment_info["totalFunding"])
    if enrichment_info.get("keyContacts"):
        lead["keyContacts"] = enrichment_info["keyContacts"]
        lead["keyContactsSource"] = enrichment_info.get("contactSource", "none")
    else:
        if "keyContacts" in lead and lead["keyContacts"]:
            filtered_contacts = []
            for contact in lead["keyContacts"]:
                c_email = str(contact.get("email", "")).strip().lower()
                c_source = str(contact.get("source", "")).strip().lower()
                
                # Filter out any unverified HTML scraped contacts if the API lookup found nothing
                if "website scraper" in c_source and (not c_email or "pending" in c_email):
                    continue
                filtered_contacts.append(contact)
            lead["keyContacts"] = filtered_contacts
    if enrichment_info.get("industry") and is_empty_value(lead.get("industry")):
        lead["industry"] = enrichment_info["industry"]
        
    # Website crawling fallback for starting/founding year
    if is_empty_value(lead.get("foundedYear")):
        web_url = lead.get("website")
        if web_url and not is_empty_value(web_url):
            crawled_year = crawl_website_for_founded_year(web_url)
            if crawled_year:
                print(f"[Enrich Team Fallback] Extracted founded year '{crawled_year}' from website: {web_url}")
                lead["foundedYear"] = str(crawled_year)
                
    db[payload.sourceUrl] = lead
    save_db(db, user_id)
    return {
        "status": "success",
        "companyName": lead.get("companyName"),
        "industry": lead.get("industry"),
        "location": lead.get("location"),
        "employeeCount": lead.get("employeeCount"),
        "foundedYear": lead.get("foundedYear"),
        "annualRevenue": lead.get("annualRevenue"),
        "totalFunding": lead.get("totalFunding"),
        "keyContacts": lead.get("keyContacts", []),
        "keyContactsSource": lead.get("keyContactsSource", "none")
    }

@router.post("/api/generate-pitch")
async def generate_pitch_endpoint(payload: GeneratePitchRequest, user_id: str = Depends(get_current_user_id)):
    db = load_db(user_id)
    if payload.sourceUrl not in db:
        raise HTTPException(status_code=404, detail="Lead not found")
        
    lead = db[payload.sourceUrl]

    # Deduct SaaS credits from user balance for the email pitch generation (Commented out for demo)
    # success, msg, info = CreditService.check_and_deduct(
    #     user_id,
    #     f"AI Outreach Pitch: {lead.get('authorName', 'Lead')}",
    #     settings.COST_AI_PITCH
    # )
    # if not success:
    #     raise HTTPException(status_code=400, detail=msg)

    author = lead.get("authorName") or "there"
    company = lead.get("companyName") or ""
    need = lead.get("needDescription") or ""
    service = lead.get("serviceRequired") or ""
    url = lead.get("sourceUrl") or ""
    
    platform_name = determine_lead_platform(url).capitalize()
    search_type = lead.get("search_type", "sales")
    
    if platform_name in ["Upwork", "Freelancer"]:
        prompt = f"""
You are an expert Freelancer and Proposal Specialist bidding on a project on {platform_name}.

Draft a highly compelling, professional, and personalized project proposal / bid cover letter to a potential client based on their job post details.

Sender Details:
- Freelancer/Agency Name: {payload.agencyName}
- Services/Specialties Offered: {payload.agencyInfo}
- Target Pitch Tone: {payload.emailTone}

Project Details:
- Platform: {platform_name}
- Project Requirements / Need: {need}
- Required Service: {service}

Instructions:
1. Keep the cover letter/proposal style matching the target tone: '{payload.emailTone}'.
   - If 'Short & Conversational': Keep it extremely concise, conversational, and direct (under 150 words).
   - If 'Professional & Formal': Use a structured layout, polite vocabulary, and formal tone.
   - If 'Value Pitch (Free Audit)': Focus on the value prop of {payload.agencyInfo}, offering high value or offering a free initial consult/mockup/audit.
2. DO NOT include a subject line since this is a proposal cover letter (not an email). Start directly with a warm greeting.
3. Reference their project description details to show that you have fully read and understood their requirements.
4. Explain how {payload.agencyName} is the best fit to solve their problem using {payload.agencyInfo}, mentioning relevant expertise.
5. Ask 1-2 clarifying questions about the project to encourage a reply.
6. Conclude with a clear, low-friction Call to Action (CTA) proposing a chat or requesting them to view your portfolio.
7. Use {payload.agencyName} in the signature. Do not include bracketed placeholders.

Format:
[Greeting & Proposal/Cover Letter Body]
"""
    elif str(search_type).lower().strip() == "recruiter":
        prompt = f"""
You are an expert HR Recruiter and Talent Acquisition Specialist.

Draft a highly personalized, warm, and compelling cold recruiting outreach email to a candidate based on their {platform_name} profile and post details.

Sender Details:
- Recruiter/Company Name: {payload.agencyName}
- Job Description / Pitch Info: {payload.agencyInfo}
- Target Email Tone: {payload.emailTone}

Recipient Details:
- Candidate Name: {author}
- Current/Previous Company or School: {company}
- Candidate Skills: {lead.get("skills", "")}
- Candidate Experience Level: {lead.get("experienceLevel", "")}
- Candidate Work Preference: {lead.get("workPreference", "")}
- Candidate location: {lead.get("location", "")}
- Post snippet describing their job hunt: {need}

Instructions:
1. Keep the email style matching the target tone: '{payload.emailTone}'.
   - If 'Short & Conversational': Keep it extremely warm, brief (under 120 words), conversational, direct, and welcoming.
   - If 'Professional & Formal': Use corporate formatting, polite vocabulary, and structured paragraphs.
   - If 'Value Pitch (Free Audit)': Focus on the career growth, culture, and projects offered by {payload.agencyName}, proposing a quick alignment call.
2. The subject line should be catchy, natural, and candidate-centric (e.g., "Exciting Role at [Company] / Saw your post", "Software Engineer opportunity at [Company]").
3. Reference their {platform_name} post or job hunt context directly to show genuine interest.
4. Pitch why {payload.agencyName} is a great fit for them, matching their skills to the job info ({payload.agencyInfo}).
5. Conclude with a low-friction Call to Action (CTA) like proposing a 10-minute introductory call.
6. Return the subject line at the top, followed by the email body. Do not include bracketed placeholders in the body—fully fill them using {payload.agencyName}. Use {payload.agencyName} in the signature.

Format:
Subject: [Subject Line]

[Email Body]
"""
    else:
        prompt = f"""
You are an expert B2B Copywriter and Sales Outreach Specialist.

Draft a highly personalized, compelling outreach email to a potential client based on their {platform_name} post details.

Sender Details:
- Agency/Sender Name: {payload.agencyName}
- Services/Specialties Offered: {payload.agencyInfo}
- Target Email Tone: {payload.emailTone}

Recipient Details:
- Author: {author}
- Company: {company}
- Need/Problem they posted about: {need}
- Service Required: {service}

Instructions:
1. Keep the email style matching the target tone: '{payload.emailTone}'.
   - If 'Short & Conversational': Keep it extremely concise (under 120 words), conversational, direct, and easy-going.
   - If 'Professional & Formal': Use corporate formatting, polite vocabulary, and structured paragraphs.
   - If 'Value Pitch (Free Audit)': Focus on the value prop of {payload.agencyInfo}, offering high value or offering a free audit/consultation.
2. The subject line should be catchy, natural, and contextually relevant (not generic).
3. Reference their {platform_name} post directly to build immediate trust.
4. Pitch how {payload.agencyName} solves their exact need using the services: {payload.agencyInfo}.
5. Conclude with a low-friction Call to Action (CTA) like proposing a 10-minute chat.
6. Return the subject line at the top, followed by the email body. Do not include bracketed placeholders like "[Your Name]" or "[Agency Name]" in the body—fully fill them using {payload.agencyName}. Use {payload.agencyName} in the signature.

Format:
Subject: [Subject Line]

[Email Body]
"""
    
    # Trigger LLM completions
    try:
        from app.qualification.lead_classifier import clean_json_response
        import httpx
        api_key = settings.GROQ_API_KEY
        pitch_content = ""
        if api_key and api_key.strip():
            url = "https://api.groq.com/openai/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
            json_payload = {
                "model": "groq/compound-mini",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.7
            }
            with httpx.Client(timeout=25.0) as client:
                res = client.post(url, headers=headers, json=json_payload)
                if res.status_code == 200:
                    pitch_content = res.json()["choices"][0]["message"]["content"]
                    
        if not pitch_content:
            url = f"{settings.OLLAMA_BASE_URL}/api/generate"
            json_payload = {
                "model": "llama3.1:8b",
                "prompt": prompt,
                "stream": False
            }
            with httpx.Client(timeout=30.0) as client:
                res = client.post(url, json=json_payload)
                if res.status_code == 200:
                    pitch_content = res.json().get("response", "")
                    
        if not pitch_content:
            raise Exception("LLM call failed.")
            
        db[payload.sourceUrl]["draftEmail"] = pitch_content
        db[payload.sourceUrl]["isConverted"] = True
        if db[payload.sourceUrl]["crmStatus"] == "New":
            db[payload.sourceUrl]["crmStatus"] = "Drafted"
            
        save_db(db, user_id)
        return {"status": "success", "pitch": pitch_content, "crmStatus": db[payload.sourceUrl]["crmStatus"]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate pitch: {str(e)}")

class SyncSheetsRequest(BaseModel):
    leads: list
    option: str
    url: str = None

@router.post("/api/sync-sheets")
async def sync_sheets_endpoint(payload: SyncSheetsRequest):
    return {"status": "success", "message": "Synced to Google Sheets"}
