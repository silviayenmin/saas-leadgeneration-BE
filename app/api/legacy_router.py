import time
import os
import json
import gspread
import imaplib
import email
import email.utils
import uuid
import datetime
import asyncio
from typing import List, Optional
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Request

from sqlalchemy.orm import Session
from app.core.outreach_db import get_outreach_db
from app.models.outreach import EmailAccount as SqlEmailAccount, OutreachSettings as SqlOutreachSettings
from app.services.outreach_crypto import outreach_crypto
from app.services.outreach_tester import test_smtp_connection, test_imap_connection

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
        
        # Load user integrations config for custom API keys
        coll_int = db_manager.get_collection("integrations")
        if coll_int is not None:
            user_cfg = coll_int.find_one({"userId": user_id}) or {}
        else:
            user_cfg = db_manager.json_db.find_one("integrations", {"userId": user_id}) or {}

        for plat in platforms:
            adapter = get_adapter(plat)
            for q in intent_queries:
                try:
                    if plat == "google_maps":
                        places_key = user_cfg.get("placesApiKey") or settings.GOOGLE_PLACES_API_KEY
                        
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
                        "leadStatus": "Warm Lead",
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
        
        # Load user's LLM configuration from integrations
        coll_int = db_manager.get_collection("integrations")
        if coll_int is not None:
            cfg = coll_int.find_one({"userId": user_id}) or {}
        else:
            cfg = db_manager.json_db.find_one("integrations", {"userId": user_id}) or {}
            
        model_conf = cfg.get("modelConfig") or {}
        active_provider = model_conf.get("active_provider", "groq")
        providers = model_conf.get("providers") or {}
        prov_conf = providers.get(active_provider) or {}
        
        # Defaults based on modelConfig
        api_model = prov_conf.get("model")
        api_temp = prov_conf.get("temperature", 0.7)
        api_url = prov_conf.get("base_url") or "http://localhost:11434"
        
        pitch_content = ""
        
        if active_provider == "groq":
            api_key = settings.GROQ_API_KEY
            if not api_model:
                api_model = "llama-3.3-70b-versatile"
                
            if api_key and api_key.strip():
                url = "https://api.groq.com/openai/v1/chat/completions"
                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                }
                json_payload = {
                    "model": api_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": api_temp
                }
                with httpx.Client(timeout=25.0) as client:
                    res = client.post(url, headers=headers, json=json_payload)
                    if res.status_code == 200:
                        pitch_content = res.json()["choices"][0]["message"]["content"]
        else:
            # Ollama
            if not api_model:
                api_model = "llama3.1:8b"
            url = f"{api_url.rstrip('/')}/api/generate"
            json_payload = {
                "model": api_model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": api_temp
                }
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
async def sync_sheets_endpoint(
    payload: SyncSheetsRequest,
    user_id: str = Depends(get_current_user_id)
):
    creds_path = "google_credentials.json"
    if not os.path.exists(creds_path):
        raise HTTPException(
            status_code=400,
            detail="Google credentials file is missing in the backend root directory. Please configure Google Sheets first."
        )

    # 1. Load user's profile details to find their email for sharing
    coll_users = db_manager.get_collection("users")
    if coll_users is not None:
        user = coll_users.find_one({"id": user_id}) or {}
    else:
        user = db_manager.json_db.find_one("users", {"id": user_id}) or {}
    user_email = user.get("email")

    try:
        # 2. Authenticate with Google Sheets service account
        gc = gspread.service_account(filename=creds_path)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Google API authentication failed: {str(e)}"
        )

    sh = None
    if payload.option == "new":
        # 3. Create a new spreadsheet
        title = f"Silvia Leads Export - {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}"
        try:
            sh = gc.create(title)
            # Share with user's email if available
            if user_email:
                try:
                    sh.share(user_email, perm_type="user", role="writer")
                except Exception as se:
                    print(f"Failed to share sheet with user {user_email}: {se}")
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to create new Google Sheet: {str(e)}"
            )
    else:
        # 4. Open an existing spreadsheet by URL or ID
        if not payload.url or not payload.url.strip():
            raise HTTPException(
                status_code=400,
                detail="A valid Google Sheet URL or ID is required for existing spreadsheet sync."
            )
        target_url = payload.url.strip()
        try:
            if "docs.google.com/spreadsheets" in target_url:
                sh = gc.open_by_url(target_url)
            else:
                sh = gc.open_by_key(target_url)
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"Could not open existing Google Sheet. Please ensure it is shared with the service account email: {str(e)}"
            )

    if not sh:
        raise HTTPException(
            status_code=500,
            detail="Failed to initialize Google Sheet workspace."
        )

    # 5. Group the leads by search query keyword
    searches = load_searches(user_id)
    url_to_keyword = {}
    for s in searches:
        kw = s.get("keyword")
        lead_urls = s.get("leadUrls") or []
        if kw:
            for u in lead_urls:
                url_to_keyword[u] = kw

    grouped_leads = {}
    for lead in payload.leads:
        url = lead.get("sourceUrl")
        kw = url_to_keyword.get(url, "Uncategorized")
        
        # Clean worksheet name (max 100 chars, no special characters disallowed by Google Sheets)
        clean_kw = re.sub(r"[\\/:\?\*\[\]]", "", kw)
        clean_kw = clean_kw.strip()[:30]  # Keep it short and neat
        if not clean_kw:
            clean_kw = "Uncategorized"
            
        if clean_kw not in grouped_leads:
            grouped_leads[clean_kw] = []
        grouped_leads[clean_kw].append(lead)

    headers = [
        "Company Name", "Location", "Phone", "Email", 
        "Rating", "Reviews", "AI Match Score", "CRM Stage", "Maps URL"
    ]

    # Keep track of created worksheets
    created_worksheets = []

    # 6. Write leads to the worksheets
    for group_name, leads_list in grouped_leads.items():
        try:
            ws = sh.worksheet(group_name)
            ws.clear()
        except gspread.exceptions.WorksheetNotFound:
            ws = sh.add_worksheet(title=group_name, rows="100", cols="20")
        
        created_worksheets.append(ws)

        # Set headers
        ws.update("A1:I1", [headers])

        # Style headers (Brand Teal #0EA5A4 background, Bold White text, Center aligned)
        ws.format("A1:I1", {
            "backgroundColor": {
                "red": 0.055,
                "green": 0.647,
                "blue": 0.643
            },
            "textFormat": {
                "bold": True,
                "foregroundColor": {
                    "red": 1.0,
                    "green": 1.0,
                    "blue": 1.0
                }
            },
            "horizontalAlignment": "CENTER"
        })

        # Write data rows
        rows = []
        for lead in leads_list:
            score = lead.get("leadScore")
            if score is None:
                score_str = "85%"
            else:
                score_str = f"{score}%"

            rows.append([
                lead.get("companyName") or "Unknown Business",
                lead.get("location") or "Not Specified",
                lead.get("phone") or "No phone",
                lead.get("contactInfo") or "No email revealed",
                lead.get("rating") or "N/A",
                lead.get("reviews") or 0,
                score_str,
                lead.get("crmStatus") or "New",
                lead.get("sourceUrl") or ""
            ])
        
        if rows:
            ws.append_rows(rows, value_input_option="USER_ENTERED")

    # Delete default Sheet1 if there are other sheets
    try:
        sheet1 = sh.worksheet("Sheet1")
        if len(sh.worksheets()) > 1:
            sh.del_worksheet(sheet1)
    except Exception:
        pass

    return {
        "status": "success",
        "message": "Synced to Google Sheets successfully",
        "spreadsheet_url": sh.url
    }

# --- OUTREACH CONFIGURATION ENDPOINTS ---

class AddAccountRequest(BaseModel):
    senderName: str
    email: str
    smtpHost: str = None
    smtpPort: int = None
    smtpUser: str = None
    smtpPass: str = None
    smtpEncryption: str = "SSL/TLS"
    imapHost: str = None
    imapPort: int = None
    imapUser: str = None
    imapPass: str = None
    imapSsl: bool = True

class TestAccountRequest(BaseModel):
    smtpHost: str = None
    smtpPort: int = None
    smtpUser: str = None
    smtpPass: str = None
    smtpEncryption: str = "SSL/TLS"
    imapHost: str = None
    imapPort: int = None
    imapUser: str = None
    imapPass: str = None
    imapSsl: bool = True

class UpdateAccountRequest(BaseModel):
    senderName: str
    email: str
    smtpHost: str = None
    smtpPort: int = None
    smtpUser: str = None
    smtpPass: str = None
    smtpEncryption: str = "SSL/TLS"
    imapHost: str = None
    imapPort: int = None
    imapUser: str = None
    imapPass: str = None
    imapSsl: bool = True

class OutreachSettingsUpdate(BaseModel):
    timezone: str
    activeDays: list
    dailyVolume: int
    minDelay: int
    maxDelay: int
    enableWarmup: bool
    warmupStart: int = None
    warmupStep: int = None
    warmupLimit: int = None
    signature: str = ""

@router.get("/api/outreach/accounts")
async def get_outreach_accounts_endpoint(
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_outreach_db)
):
    accounts = db.query(SqlEmailAccount).filter(SqlEmailAccount.user_id == user_id).all()
    results = []
    for a in accounts:
        results.append({
            "id": a.id,
            "senderName": a.sender_name,
            "email": a.email_address,
            "smtpHost": a.smtp_host,
            "smtpPort": a.smtp_port,
            "smtpUser": a.smtp_username,
            "smtpPass": "********",
            "smtpEncryption": a.smtp_encryption,
            "imapHost": a.imap_host,
            "imapPort": a.imap_port,
            "imapUser": a.imap_username,
            "imapPass": "********",
            "imapSsl": a.imap_ssl,
            "isActive": a.is_active,
            "smtpStatus": "Connected",
            "imapStatus": "Connected",
            "dailySent": 0,
            "dailyLimit": 100
        })
    return {"status": "success", "accounts": results}

@router.post("/api/outreach/accounts/test")
async def test_outreach_account_endpoint(payload: TestAccountRequest):
    smtp_res = test_smtp_connection(
        host=payload.smtpHost,
        port=payload.smtpPort,
        username=payload.smtpUser,
        password=payload.smtpPass,
        encryption=payload.smtpEncryption
    )
    imap_res = test_imap_connection(
        host=payload.imapHost,
        port=payload.imapPort,
        username=payload.imapUser,
        password=payload.imapPass,
        use_ssl=payload.imapSsl
    )
    
    smtp_status = "Connected" if smtp_res["status"] == "success" else f"Failed: {smtp_res['message']}"
    imap_status = "Connected" if imap_res["status"] == "success" else f"Failed: {imap_res['message']}"
    
    return {
        "status": "success" if (smtp_res["status"] == "success" and imap_res["status"] == "success") else "error",
        "smtpStatus": smtp_status,
        "imapStatus": imap_status,
        "smtpError": smtp_res.get("message") if smtp_res["status"] == "error" else None,
        "imapError": imap_res.get("message") if imap_res["status"] == "error" else None
    }

@router.post("/api/outreach/accounts")
async def add_outreach_account_endpoint(
    payload: AddAccountRequest, 
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_outreach_db)
):
    # Check if duplicate email already exists in SQLite EmailAccount table
    existing = db.query(SqlEmailAccount).filter(SqlEmailAccount.email_address == payload.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="An email account with this email address already exists.")
        
    # Run connection test first before saving
    smtp_res = test_smtp_connection(
        host=payload.smtpHost,
        port=payload.smtpPort,
        username=payload.smtpUser,
        password=payload.smtpPass,
        encryption=payload.smtpEncryption
    )
    if smtp_res["status"] == "error":
        raise HTTPException(status_code=400, detail=f"SMTP Validation failed: {smtp_res['message']}")
        
    imap_res = test_imap_connection(
        host=payload.imapHost,
        port=payload.imapPort,
        username=payload.imapUser,
        password=payload.imapPass,
        use_ssl=payload.imapSsl
    )
    if imap_res["status"] == "error":
        raise HTTPException(status_code=400, detail=f"IMAP Validation failed: {imap_res['message']}")
        
    # Encrypt credentials
    smtp_enc = outreach_crypto.encrypt(payload.smtpPass)
    imap_enc = outreach_crypto.encrypt(payload.imapPass)
    
    new_acc = SqlEmailAccount(
        user_id=user_id,
        sender_name=payload.senderName.strip(),
        email_address=payload.email.strip(),
        smtp_host=payload.smtpHost.strip(),
        smtp_port=payload.smtpPort,
        smtp_username=payload.smtpUser.strip(),
        smtp_password_encrypted=smtp_enc,
        smtp_encryption=payload.smtpEncryption.strip(),
        imap_host=payload.imapHost.strip(),
        imap_port=payload.imapPort,
        imap_username=payload.imapUser.strip(),
        imap_password_encrypted=imap_enc,
        imap_ssl=payload.imapSsl
    )
    
    db.add(new_acc)
    db.commit()
    db.refresh(new_acc)
    
    return {
        "status": "success",
        "account": {
            "id": new_acc.id,
            "senderName": new_acc.sender_name,
            "email": new_acc.email_address,
            "smtpHost": new_acc.smtp_host,
            "smtpPort": new_acc.smtp_port,
            "smtpUser": new_acc.smtp_username,
            "smtpPass": "********",
            "smtpEncryption": new_acc.smtp_encryption,
            "imapHost": new_acc.imap_host,
            "imapPort": new_acc.imap_port,
            "imapUser": new_acc.imap_username,
            "imapPass": "********",
            "imapSsl": new_acc.imap_ssl,
            "isActive": new_acc.is_active,
            "smtpStatus": "Connected",
            "imapStatus": "Connected",
            "dailySent": 0,
            "dailyLimit": 100
        }
    }

@router.put("/api/outreach/accounts/{acc_id}")
async def update_outreach_account_endpoint(
    acc_id: str, 
    payload: UpdateAccountRequest, 
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_outreach_db)
):
    acc = db.query(SqlEmailAccount).filter(SqlEmailAccount.id == acc_id, SqlEmailAccount.user_id == user_id).first()
    if not acc:
        raise HTTPException(status_code=404, detail="Account not found")
        
    acc.sender_name = payload.senderName.strip()
    acc.email_address = payload.email.strip()
    acc.smtp_host = payload.smtpHost.strip()
    acc.smtp_port = payload.smtpPort
    acc.smtp_username = payload.smtpUser.strip()
    acc.smtp_encryption = payload.smtpEncryption.strip()
    acc.imap_host = payload.imapHost.strip()
    acc.imap_port = payload.imapPort
    acc.imap_username = payload.imapUser.strip()
    acc.imap_ssl = payload.imapSsl
    
    if payload.smtpPass != "********" and payload.smtpPass.strip():
        acc.smtp_password_encrypted = outreach_crypto.encrypt(payload.smtpPass)
    if payload.imapPass != "********" and payload.imapPass.strip():
        acc.imap_password_encrypted = outreach_crypto.encrypt(payload.imapPass)
        
    db.commit()
    db.refresh(acc)
    
    return {
        "status": "success",
        "account": {
            "id": acc.id,
            "senderName": acc.sender_name,
            "email": acc.email_address,
            "smtpHost": acc.smtp_host,
            "smtpPort": acc.smtp_port,
            "smtpUser": acc.smtp_username,
            "smtpPass": "********",
            "smtpEncryption": acc.smtp_encryption,
            "imapHost": acc.imap_host,
            "imapPort": acc.imap_port,
            "imapUser": acc.imap_username,
            "imapPass": "********",
            "imapSsl": acc.imap_ssl,
            "isActive": acc.is_active,
            "smtpStatus": "Connected",
            "imapStatus": "Connected",
            "dailySent": 0,
            "dailyLimit": 100
        }
    }

@router.put("/api/outreach/accounts/{acc_id}/toggle")
async def toggle_outreach_account_endpoint(
    acc_id: str, 
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_outreach_db)
):
    acc = db.query(SqlEmailAccount).filter(SqlEmailAccount.id == acc_id, SqlEmailAccount.user_id == user_id).first()
    if not acc:
        raise HTTPException(status_code=404, detail="Account not found")
        
    acc.is_active = not acc.is_active
    db.commit()
    db.refresh(acc)
    
    return {"status": "success", "isActive": acc.is_active}

@router.delete("/api/outreach/accounts/{acc_id}")
async def delete_outreach_account_endpoint(
    acc_id: str, 
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_outreach_db)
):
    acc = db.query(SqlEmailAccount).filter(SqlEmailAccount.id == acc_id, SqlEmailAccount.user_id == user_id).first()
    if not acc:
        raise HTTPException(status_code=404, detail="Account not found")
        
    db.delete(acc)
    db.commit()
    
    return {"status": "success", "message": "Account deleted successfully"}

@router.get("/api/outreach/settings")
async def get_outreach_settings_endpoint(
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_outreach_db)
):
    settings = db.query(SqlOutreachSettings).filter(SqlOutreachSettings.user_id == user_id).first()
    if not settings:
        default_settings = {
            "timezone": "UTC",
            "activeDays": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
            "dailyVolume": 150,
            "minDelay": 60,
            "maxDelay": 300,
            "enableWarmup": True,
            "warmupStart": 10,
            "warmupStep": 5,
            "warmupLimit": 50,
            "signature": "<p>Best regards,<br><strong>{{sender_name}}</strong><br>{{job_title}} at {{company}}</p>"
        }
        return {"status": "success", "settings": default_settings}
        
    return {
        "status": "success",
        "settings": {
            "timezone": settings.timezone,
            "activeDays": settings.active_days or [],
            "dailyVolume": settings.max_emails_per_day,
            "minDelay": settings.min_delay_seconds,
            "maxDelay": settings.max_delay_seconds,
            "signature": settings.signature_html or "",
            "enableWarmup": settings.enable_warmup,
            "warmupStart": settings.warmup_start_count,
            "warmupStep": settings.warmup_daily_increase,
            "warmupLimit": settings.warmup_max_count
        }
    }

@router.put("/api/outreach/settings")
async def update_outreach_settings_endpoint(
    payload: OutreachSettingsUpdate, 
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_outreach_db)
):
    settings = db.query(SqlOutreachSettings).filter(SqlOutreachSettings.user_id == user_id).first()
    if not settings:
        settings = SqlOutreachSettings(user_id=user_id)
        db.add(settings)
        
    settings.timezone = payload.timezone
    settings.active_days = payload.activeDays
    settings.max_emails_per_day = payload.dailyVolume
    settings.min_delay_seconds = payload.minDelay
    settings.max_delay_seconds = payload.maxDelay
    settings.signature_html = payload.signature
    settings.enable_warmup = payload.enableWarmup
    settings.warmup_start_count = payload.warmupStart
    settings.warmup_daily_increase = payload.warmupStep
    settings.warmup_max_count = payload.warmupLimit
    
    db.commit()
    db.refresh(settings)
    
    return {
        "status": "success",
        "settings": {
            "timezone": settings.timezone,
            "activeDays": settings.active_days or [],
            "dailyVolume": settings.max_emails_per_day,
            "minDelay": settings.min_delay_seconds,
            "maxDelay": settings.max_delay_seconds,
            "signature": settings.signature_html or "",
            "enableWarmup": settings.enable_warmup,
            "warmupStart": settings.warmup_start_count,
            "warmupStep": settings.warmup_daily_increase,
            "warmupLimit": settings.warmup_max_count
        }
    }

# --- TEMPLATE OUTREACH CONFIGURATION ENDPOINTS ---

class OutreachConfigPayload(BaseModel):
    imap_server: str
    imap_port: str
    imap_email: str
    imap_password: str

class WebhookConfigPayload(BaseModel):
    webhook_url: str

class PlacesConfigPayload(BaseModel):
    places_api_key: str

class TwitterConfigPayload(BaseModel):
    twitter_api_key: str

class ModelConfigPayload(BaseModel):
    active_provider: str
    providers: dict
    workspace_dir: Optional[str] = "output"
    memory: Optional[dict] = None

class GoogleSheetsConfigPayload(BaseModel):
    sheet_id: str

class UpdateProfileRequest(BaseModel):
    displayName: Optional[str] = None
    businessName: Optional[str] = None
    agencyInfo: Optional[str] = None

@router.get("/api/user/profile")
async def get_user_profile_endpoint(user_id: str = Depends(get_current_user_id)):
    # Get user details
    coll_users = db_manager.get_collection("users")
    if coll_users is not None:
        user = coll_users.find_one({"id": user_id})
    else:
        user = db_manager.json_db.find_one("users", {"id": user_id})
        
    if not user:
        user = {}
        
    # Get counts
    coll_leads = db_manager.get_collection("leads")
    coll_searches = db_manager.get_collection("searches")
    
    if coll_leads is not None:
        leads_count = coll_leads.count_documents({"userId": user_id})
        qualified_count = coll_leads.count_documents({
            "userId": user_id, 
            "leadCategory": {"$in": ["High Intent", "Medium Intent"]}
        })
        drafted_count = coll_leads.count_documents({
            "userId": user_id,
            "crmStatus": {"$in": ["Drafted", "drafted"]}
        })
        emailed_count = coll_leads.count_documents({
            "userId": user_id,
            "crmStatus": {"$in": ["Emailed", "emailed"]}
        })
        replied_count = coll_leads.count_documents({
            "userId": user_id,
            "crmStatus": {"$in": ["Replied", "replied"]}
        })
    else:
        leads_list = db_manager.json_db.find("leads", {"userId": user_id})
        leads_count = len(leads_list)
        qualified_count = len([l for l in leads_list if l.get("leadCategory") in ["High Intent", "Medium Intent"]])
        drafted_count = len([l for l in leads_list if l.get("crmStatus") in ["Drafted", "drafted"]])
        emailed_count = len([l for l in leads_list if l.get("crmStatus") in ["Emailed", "emailed"]])
        replied_count = len([l for l in leads_list if l.get("crmStatus") in ["Replied", "replied"]])
        
    if coll_searches is not None:
        scans_count = coll_searches.count_documents({"userId": user_id})
    else:
        scans_count = len(db_manager.json_db.find("searches", {"userId": user_id}))
        
    rate = int((qualified_count / leads_count) * 100) if leads_count > 0 else 0
    
    # Load integrations to find webhookUrl
    coll_int = db_manager.get_collection("integrations")
    if coll_int is not None:
        cfg = coll_int.find_one({"userId": user_id}) or {}
    else:
        cfg = db_manager.json_db.find_one("integrations", {"userId": user_id}) or {}
        
    return {
        "status": "success",
        "profile": {
            "email": user.get("email") or "user@mapflow-ai.com",
            "displayName": user.get("fullName") or (user.get("email") or "user").split("@")[0].capitalize(),
            "businessName": user.get("companyName") or "My Business",
            "agencyInfo": user.get("bio") or "premier design & development services",
            "joinedDate": user.get("createdAt") or datetime.datetime.utcnow().isoformat(),
            "apiToken": user_id,
            "webhookUrl": cfg.get("webhookUrl") or ""
        },
        "stats": {
            "scansCount": scans_count,
            "leadsCount": leads_count,
            "qualifiedLeadsCount": qualified_count,
            "qualificationRate": rate,
            "draftedCount": drafted_count,
            "emailedCount": emailed_count,
            "repliedCount": replied_count
        }
    }

@router.post("/api/user/profile/update")
async def update_user_profile_endpoint(payload: UpdateProfileRequest, user_id: str = Depends(get_current_user_id)):
    coll_users = db_manager.get_collection("users")
    update_data = {}
    if payload.displayName is not None:
        update_data["fullName"] = payload.displayName.strip()
    if payload.businessName is not None:
        update_data["companyName"] = payload.businessName.strip()
    if payload.agencyInfo is not None:
        update_data["bio"] = payload.agencyInfo.strip()
        
    if update_data:
        if coll_users is not None:
            coll_users.update_one({"id": user_id}, {"$set": update_data})
        else:
            db_manager.json_db.update_one("users", {"id": user_id}, {"$set": update_data})
            
    return {"status": "success", "message": "Profile updated successfully"}

@router.get("/api/outreach/config")
async def get_outreach_config_endpoint(user_id: str = Depends(get_current_user_id)):
    coll = db_manager.get_collection("integrations")
    if coll is not None:
        cfg = coll.find_one({"userId": user_id}) or {}
    else:
        cfg = db_manager.json_db.find_one("integrations", {"userId": user_id}) or {}
        
    return {
        "status": "success",
        "config": {
            "imap_server": cfg.get("imapHost") or "",
            "imap_port": cfg.get("imapPort") or "993",
            "imap_email": cfg.get("imapUsername") or "",
            "imap_password": "********" if cfg.get("imapPassword") else ""
        }
    }

@router.post("/api/outreach/config")
async def save_outreach_config_endpoint(payload: OutreachConfigPayload, user_id: str = Depends(get_current_user_id)):
    coll = db_manager.get_collection("integrations")
    
    update_data = {
        "imapHost": payload.imap_server.strip(),
        "imapPort": payload.imap_port.strip(),
        "imapUsername": payload.imap_email.strip()
    }
    
    # Check if we should update password
    if payload.imap_password != "********" and payload.imap_password.strip():
        update_data["imapPassword"] = payload.imap_password
        
    if coll is not None:
        coll.update_one({"userId": user_id}, {"$set": update_data}, upsert=True)
    else:
        existing = db_manager.json_db.find_one("integrations", {"userId": user_id})
        if existing:
            db_manager.json_db.update_one("integrations", {"userId": user_id}, {"$set": update_data})
        else:
            update_data["userId"] = user_id
            db_manager.json_db.insert_one("integrations", update_data)
            
    return {"status": "success", "message": "Email settings saved successfully"}

async def trigger_replied_webhook(webhook_url: str, lead_data: dict):
    if not webhook_url:
        return
    try:
        import httpx
        async with httpx.AsyncClient(timeout=5) as client:
            payload = {
                "event": "lead.replied",
                "timestamp": datetime.datetime.utcnow().isoformat(),
                "lead": {
                    "companyName": lead_data.get("companyName"),
                    "email": lead_data.get("contactInfo"),
                    "location": lead_data.get("location"),
                    "phone": lead_data.get("phone"),
                    "crmStatus": "Replied",
                    "receivedReplies": lead_data.get("receivedReplies", [])
                }
            }
            await client.post(webhook_url, json=payload)
    except Exception as e:
        print(f"Failed to trigger webhook for {webhook_url}: {e}")

async def sync_replies_for_user(user_id: str, cfg: dict) -> dict:
    imap_host = cfg.get("imapHost")
    imap_port_str = cfg.get("imapPort") or "993"
    imap_email = cfg.get("imapUsername")
    imap_password = cfg.get("imapPassword")
    webhook_url = cfg.get("webhookUrl")
    
    if not imap_host or not imap_email or not imap_password:
        return {"status": "success", "newRepliesCount": 0, "replies": []}
        
    try:
        imap_port = int(imap_port_str)
    except ValueError:
        imap_port = 993

    # Connect to the IMAP server
    try:
        mail = imaplib.IMAP4_SSL(imap_host, imap_port, timeout=15)
        mail.login(imap_email, imap_password)
        mail.select("inbox")
    except Exception as e:
        print(f"IMAP connection failed for user {user_id}: {e}")
        return {"status": "error", "message": f"Connection failed: {str(e)}"}

    # Search for emails in last 14 days
    since_date = (datetime.date.today() - datetime.timedelta(days=14)).strftime("%d-%b-%Y")
    try:
        status, messages = mail.search(None, f'(SINCE "{since_date}")')
        if status != "OK":
            mail.close()
            mail.logout()
            return {"status": "success", "newRepliesCount": 0, "replies": []}
    except Exception as e:
        print(f"IMAP search failed for user {user_id}: {e}")
        try:
            mail.close()
            mail.logout()
        except Exception:
            pass
        return {"status": "error", "message": f"Search failed: {str(e)}"}

    email_ids = messages[0].split()
    inbox_emails = {}
    
    # Iterate over the messages to fetch headers in a single batch call
    if email_ids:
        message_set = b",".join(email_ids)
        try:
            res, msg_data = mail.fetch(message_set, '(RFC822.HEADER)')
            if res == "OK":
                for response_part in msg_data:
                    if isinstance(response_part, tuple):
                        # Extract the mail ID from the response part prefix (e.g. b'123 (RFC822.HEADER {456}')
                        part_prefix = response_part[0].decode("utf-8", errors="ignore")
                        id_match = re.match(r'^(\d+)', part_prefix)
                        if not id_match:
                            continue
                        curr_mail_id = id_match.group(1).encode("utf-8")
                        
                        msg = email.message_from_bytes(response_part[1])
                        from_header = msg.get("From")
                        subject_header = msg.get("Subject")
                        date_header = msg.get("Date")
                        
                        if not from_header:
                            continue
                        
                        # Extract email address
                        email_match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', from_header)
                        if not email_match:
                            continue
                        sender_email = email_match.group(0).lower().strip()
                        
                        # Decode subject header
                        subject_str = "Re: Outreach"
                        if subject_header:
                            try:
                                decoded_parts = email.header.decode_header(subject_header)
                                subject_parts = []
                                for part, encoding in decoded_parts:
                                    if isinstance(part, bytes):
                                        subject_parts.append(part.decode(encoding or "utf-8", errors="ignore"))
                                    else:
                                        subject_parts.append(str(part))
                                subject_str = "".join(subject_parts)
                            except Exception:
                                subject_str = str(subject_header)
                                
                        # Parse date header
                        parsed_date = datetime.datetime.utcnow().isoformat()
                        if date_header:
                            try:
                                t = email.utils.parsedate_to_datetime(date_header)
                                parsed_date = t.isoformat()
                            except Exception:
                                pass
                                
                        if sender_email not in inbox_emails:
                            inbox_emails[sender_email] = []
                        
                        inbox_emails[sender_email].append({
                            "id": curr_mail_id,
                            "subject": subject_str,
                            "receivedAt": parsed_date
                        })
        except Exception as e:
            print(f"Error reading batch email headers: {e}")

    # Cross-reference with our Leads DB
    db = load_db(user_id)
    new_replies = []
    
    # helper normalization functions
    def normalize_subject(subj: str) -> str:
        if not subj:
            return ""
        subj = subj.lower()
        subj = re.sub(r'^(re|fwd|fw|reply|re-reply|aw|wg)\s*:\s*', '', subj)
        subj = re.sub(r'[^a-z0-9]', '', subj)
        return subj

    def extract_original_subject(draft_email: str) -> str:
        if not draft_email:
            return ""
        lines = draft_email.split("\n")
        for line in lines:
            if line.lower().startswith("subject:"):
                return line[len("subject:"):].strip()
        return ""

    def clean_reply_body(body_text: str) -> str:
        if not body_text:
            return ""
        body_text = re.split(r'-{3,}\s*Original Message\s*-{3,}', body_text, flags=re.IGNORECASE)[0]
        body_text = re.split(r'^On\s+.*wrote:\s*$', body_text, flags=re.MULTILINE | re.IGNORECASE)[0]
        body_text = re.split(r'^\s*From:\s+.*$', body_text, flags=re.MULTILINE | re.IGNORECASE)[0]
        body_text = re.split(r'^_{3,}\s*$', body_text, flags=re.MULTILINE)[0]
        return body_text.strip()

    for lead in db.values():
        lead_email = (lead.get("contactInfo") or "").lower().strip()
        if not lead_email:
            continue
            
        if lead_email in inbox_emails:
            matching_messages = inbox_emails[lead_email]
            
            # Check subject matches
            original_subject = extract_original_subject(lead.get("draftEmail") or "")
            norm_original = normalize_subject(original_subject)
            
            if "receivedReplies" not in lead:
                lead["receivedReplies"] = []
                
            existing_dates = {r.get("receivedAt") for r in lead["receivedReplies"]}
            
            for msg_meta in matching_messages:
                # Subject matching constraint: if there is an original subject, match it!
                if norm_original:
                    norm_received = normalize_subject(msg_meta["subject"])
                    if norm_original not in norm_received and norm_received not in norm_original:
                        continue
                
                if msg_meta["receivedAt"] in existing_dates:
                    continue
                    
                body_content = "No body content"
                try:
                    res, body_data = mail.fetch(msg_meta["id"], '(RFC822)')
                    if res == "OK":
                        for response_part in body_data:
                            if isinstance(response_part, tuple):
                                full_msg = email.message_from_bytes(response_part[1])
                                if full_msg.is_multipart():
                                    for part in full_msg.walk():
                                        content_type = part.get_content_type()
                                        content_disposition = str(part.get("Content-Disposition"))
                                        if content_type == "text/plain" and "attachment" not in content_disposition:
                                            try:
                                                body_content = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", errors="ignore")
                                                break
                                            except Exception:
                                                pass
                                else:
                                    try:
                                        body_content = full_msg.get_payload(decode=True).decode(full_msg.get_content_charset() or "utf-8", errors="ignore")
                                    except Exception:
                                        pass
                except Exception as body_err:
                    print(f"Failed to fetch body for email {msg_meta['id']}: {body_err}")
                
                # Clean and strip reply quotes
                cleaned_body = clean_reply_body(body_content)
                if len(cleaned_body) > 1000:
                    cleaned_body = cleaned_body[:1000] + "... (truncated)"
                    
                new_reply_obj = {
                    "subject": msg_meta["subject"],
                    "receivedAt": msg_meta["receivedAt"],
                    "body": cleaned_body
                }
                
                lead["receivedReplies"].append(new_reply_obj)
                lead["crmStatus"] = "Replied"
                
                new_replies.append({
                    "companyName": lead.get("companyName") or "Unknown Business",
                    "email": lead_email
                })
                
                # Trigger system notification / webhook
                if webhook_url:
                    try:
                        asyncio.create_task(trigger_replied_webhook(webhook_url, lead))
                    except Exception as we:
                        print(f"Failed to trigger webhook task: {we}")
                
    if new_replies:
        save_db(db, user_id)

    try:
        mail.close()
        mail.logout()
    except Exception:
        pass

    return {
        "status": "success",
        "newRepliesCount": len(new_replies),
        "replies": new_replies
    }

async def imap_background_worker_loop():
    await asyncio.sleep(15)  # Wait for startup connections to settle
    while True:
        try:
            print("[Background worker] Running periodic IMAP reply synchronization...")
            coll = db_manager.get_collection("integrations")
            if coll is not None:
                all_configs = list(coll.find({}))
            else:
                all_configs = db_manager.json_db.find("integrations", {})
                
            for cfg in all_configs:
                user_id = cfg.get("userId")
                if not user_id:
                    continue
                await sync_replies_for_user(user_id, cfg)
        except Exception as e:
            print(f"[Background worker] Error in IMAP synchronization task: {e}")
            
        # Sleep for 10 minutes (600 seconds)
        await asyncio.sleep(600)

@router.on_event("startup")
async def startup_event():
    asyncio.create_task(imap_background_worker_loop())

@router.post("/api/outreach/sync-replies")
async def sync_replies_endpoint(user_id: str = Depends(get_current_user_id)):
    # 1. Load user's integrations configuration
    coll = db_manager.get_collection("integrations")
    if coll is not None:
        cfg = coll.find_one({"userId": user_id}) or {}
    else:
        cfg = db_manager.json_db.find_one("integrations", {"userId": user_id}) or {}
        
    res = await sync_replies_for_user(user_id, cfg)
    if res.get("status") == "error":
        raise HTTPException(status_code=500, detail=res.get("message"))
    return res

@router.get("/api/model-config")
async def get_model_config_endpoint(user_id: str = Depends(get_current_user_id)):
    coll = db_manager.get_collection("integrations")
    if coll is not None:
        cfg = coll.find_one({"userId": user_id}) or {}
    else:
        cfg = db_manager.json_db.find_one("integrations", {"userId": user_id}) or {}
        
    default_config = {
        "active_provider": "groq",
        "providers": {
            "groq": {
                "model": "llama-3.3-70b-versatile",
                "temperature": 0.7
            }
        }
    }
    return cfg.get("modelConfig") or default_config

@router.post("/api/model-config")
async def update_model_config_endpoint(payload: ModelConfigPayload, user_id: str = Depends(get_current_user_id)):
    coll = db_manager.get_collection("integrations")
    
    update_data = {
        "modelConfig": payload.dict()
    }
    
    if coll is not None:
        coll.update_one({"userId": user_id}, {"$set": update_data}, upsert=True)
    else:
        existing = db_manager.json_db.find_one("integrations", {"userId": user_id})
        if existing:
            db_manager.json_db.update_one("integrations", {"userId": user_id}, {"$set": update_data})
        else:
            update_data["userId"] = user_id
            db_manager.json_db.insert_one("integrations", update_data)
            
    return {"status": "success", "config": payload.dict()}

@router.get("/api/outreach/places")
async def get_places_endpoint(user_id: str = Depends(get_current_user_id)):
    coll = db_manager.get_collection("integrations")
    if coll is not None:
        cfg = coll.find_one({"userId": user_id}) or {}
    else:
        cfg = db_manager.json_db.find_one("integrations", {"userId": user_id}) or {}
        
    api_key = cfg.get("googlePlacesApiKey") or ""
    masked_key = ""
    if api_key:
        if len(api_key) <= 8:
            masked_key = "********"
        else:
            masked_key = f"{api_key[:4]}********{api_key[-4:]}"
            
    return {"status": "success", "places_api_key": masked_key, "is_configured": bool(api_key)}

@router.post("/api/outreach/places")
async def save_places_endpoint(payload: PlacesConfigPayload, user_id: str = Depends(get_current_user_id)):
    coll = db_manager.get_collection("integrations")
    key_to_save = payload.places_api_key.strip()
    
    if "********" in key_to_save:
        # Keep existing key
        if coll is not None:
            cfg = coll.find_one({"userId": user_id}) or {}
        else:
            cfg = db_manager.json_db.find_one("integrations", {"userId": user_id}) or {}
        key_to_save = cfg.get("googlePlacesApiKey") or ""
        
    update_data = {"googlePlacesApiKey": key_to_save}
    
    if coll is not None:
        coll.update_one({"userId": user_id}, {"$set": update_data}, upsert=True)
    else:
        existing = db_manager.json_db.find_one("integrations", {"userId": user_id})
        if existing:
            db_manager.json_db.update_one("integrations", {"userId": user_id}, {"$set": update_data})
        else:
            update_data["userId"] = user_id
            db_manager.json_db.insert_one("integrations", update_data)
            
    return {"status": "success", "message": "Places API Key saved successfully"}

@router.get("/api/outreach/twitter")
async def get_twitter_endpoint(user_id: str = Depends(get_current_user_id)):
    coll = db_manager.get_collection("integrations")
    if coll is not None:
        cfg = coll.find_one({"userId": user_id}) or {}
    else:
        cfg = db_manager.json_db.find_one("integrations", {"userId": user_id}) or {}
        
    api_key = cfg.get("twitterApiKey") or ""
    masked_key = ""
    if api_key:
        if len(api_key) <= 8:
            masked_key = "********"
        else:
            masked_key = f"{api_key[:4]}********{api_key[-4:]}"
            
    return {"status": "success", "twitter_api_key": masked_key, "is_configured": bool(api_key)}

@router.post("/api/outreach/twitter")
async def save_twitter_endpoint(payload: TwitterConfigPayload, user_id: str = Depends(get_current_user_id)):
    coll = db_manager.get_collection("integrations")
    key_to_save = payload.twitter_api_key.strip()
    
    if "********" in key_to_save:
        # Keep existing key
        if coll is not None:
            cfg = coll.find_one({"userId": user_id}) or {}
        else:
            cfg = db_manager.json_db.find_one("integrations", {"userId": user_id}) or {}
        key_to_save = cfg.get("twitterApiKey") or ""
        
    update_data = {"twitterApiKey": key_to_save}
    
    if coll is not None:
        coll.update_one({"userId": user_id}, {"$set": update_data}, upsert=True)
    else:
        existing = db_manager.json_db.find_one("integrations", {"userId": user_id})
        if existing:
            db_manager.json_db.update_one("integrations", {"userId": user_id}, {"$set": update_data})
        else:
            update_data["userId"] = user_id
            db_manager.json_db.insert_one("integrations", update_data)
            
    return {"status": "success", "message": "Twitter API Key saved successfully"}

@router.get("/api/outreach/webhook")
async def get_webhook_endpoint(user_id: str = Depends(get_current_user_id)):
    coll = db_manager.get_collection("integrations")
    if coll is not None:
        cfg = coll.find_one({"userId": user_id}) or {}
    else:
        cfg = db_manager.json_db.find_one("integrations", {"userId": user_id}) or {}
        
    return {"status": "success", "webhook_url": cfg.get("webhookUrl") or ""}

@router.post("/api/outreach/webhook")
async def save_webhook_endpoint(payload: WebhookConfigPayload, user_id: str = Depends(get_current_user_id)):
    coll = db_manager.get_collection("integrations")
    update_data = {"webhookUrl": payload.webhook_url.strip()}
    
    if coll is not None:
        coll.update_one({"userId": user_id}, {"$set": update_data}, upsert=True)
    else:
        existing = db_manager.json_db.find_one("integrations", {"userId": user_id})
        if existing:
            db_manager.json_db.update_one("integrations", {"userId": user_id}, {"$set": update_data})
        else:
            update_data["userId"] = user_id
            db_manager.json_db.insert_one("integrations", update_data)
            
    return {"status": "success", "message": "Webhook URL saved successfully"}

@router.get("/api/config/google-sheets")
async def get_google_sheets_config_endpoint(user_id: str = Depends(get_current_user_id)):
    coll = db_manager.get_collection("integrations")
    if coll is not None:
        cfg = coll.find_one({"userId": user_id}) or {}
    else:
        cfg = db_manager.json_db.find_one("integrations", {"userId": user_id}) or {}
        
    sheet_id = cfg.get("googleSheetId") or ""
    
    # Check if google_credentials.json file exists
    creds_path = "google_credentials.json"
    credentials_active = os.path.exists(creds_path)
    
    client_email = None
    if credentials_active:
        try:
            with open(creds_path, "r") as f:
                creds_data = json.load(f)
                client_email = creds_data.get("client_email")
        except Exception:
            client_email = "google-sheets-sync@mapflow-ai.iam.gserviceaccount.com"
    
    return {
        "status": "success",
        "sheet_id": sheet_id,
        "client_email": client_email,
        "credentials_active": credentials_active
    }

@router.post("/api/config/google-sheets")
async def save_google_sheets_config_endpoint(payload: GoogleSheetsConfigPayload, user_id: str = Depends(get_current_user_id)):
    coll = db_manager.get_collection("integrations")
    update_data = {"googleSheetId": payload.sheet_id.strip()}
    
    if coll is not None:
        coll.update_one({"userId": user_id}, {"$set": update_data}, upsert=True)
    else:
        existing = db_manager.json_db.find_one("integrations", {"userId": user_id})
        if existing:
            db_manager.json_db.update_one("integrations", {"userId": user_id}, {"$set": update_data})
        else:
            update_data["userId"] = user_id
            db_manager.json_db.insert_one("integrations", update_data)
            
    return {"status": "success", "message": "Google Sheet ID saved successfully"}
