EMPTY_VALUES = {"", "none", "unknown", "not specified", "no company details", "linkedin", "facebook", "twitter", "reddit", "unknown poster", "anywhere", "remote"}
def is_empty_value(v): 
    return not v or str(v).strip().lower() in EMPTY_VALUES

def calculate_lead_score(lead: dict) -> dict:
    search_type = lead.get("search_type", "sales")
    if str(search_type).lower().strip() == "recruiter":
        intent_score = 0
        intent_type = lead.get("intentType", "General Discussion")
        buying_intent = lead.get("buyingIntent", "Low")
        
        if intent_type in ["Candidate/Job Seeker", "Portfolio Share"]:
            intent_score = 40
        elif intent_type == "Career Discussion":
            intent_score = 30
        else:
            bi = str(buying_intent).lower()
            if bi in ["high", "hiring"]:
                intent_score = 40
            elif bi in ["medium", "warm", "research", "potential"]:
                intent_score = 25
            else:
                intent_score = 10
                
        # Skills Mentioned - 20 points
        skills = str(lead.get("skills", "")).strip()
        skills_score = 20 if skills and not is_empty_value(skills) else 0
        
        # Work Preference Present - 15 points
        pref = str(lead.get("workPreference", "")).strip()
        pref_score = 15 if pref and pref.lower() not in ["", "none", "unknown"] else 0
        
        # Company/School Mentioned - 10 points
        company = str(lead.get("companyName", "")).strip()
        company_score = 10 if company and not is_empty_value(company) and company.lower() != "not specified" else 0
        
        # Location Mentioned - 5 points
        loc = str(lead.get("location", "")).strip()
        location_score = 5 if loc and not is_empty_value(loc) else 0
        
        # Author Identified - 10 points
        author = str(lead.get("authorName", "")).strip()
        author_score = 10 if author and not is_empty_value(author) else 0
        
        total_score = intent_score + skills_score + pref_score + company_score + location_score + author_score
        
        bi_clean = str(buying_intent).strip().lower()
        it_clean = str(intent_type).strip().lower()
        if bi_clean in ["none", "low"] or it_clean in ["general discussion", "none"]:
            category = "Low Intent"
            total_score = min(total_score, 35)
        else:
            if total_score >= 70:
                category = "High Intent"
            elif total_score >= 40:
                category = "Medium Intent"
            else:
                category = "Low Intent"
                
        lead["leadScore"] = total_score
        lead["leadCategory"] = category
        return lead

    # Standard Sales Scoring (search_type == "sales")
    intent_score = 0
    intent_type = lead.get("intentType", "General Discussion")
    buying_intent = lead.get("buyingIntent", "Low")
    
    # Intent type / Buying Intent - 40 points
    if intent_type in ["Looking For Service", "Recommendation Request"]:
        intent_score = 40
    elif intent_type in ["Hiring Signal", "Expansion Signal", "Funding Signal"]:
        intent_score = 30
    else:
        # Fallback to checking text values
        bi = str(buying_intent).lower()
        if bi in ["high", "hiring", "qualified"]:
            intent_score = 40
        elif bi in ["medium", "warm", "moderate"]:
            intent_score = 25
        else:
            intent_score = 10

    # Service Required Mentioned - 20 points
    service = str(lead.get("serviceRequired", "")).strip()
    service_score = 20 if service and not is_empty_value(service) and service.lower() != "no" else 0

    # Need Description Present - 15 points
    need = str(lead.get("needDescription", "")).strip()
    need_score = 15 if need and len(need) > 10 and not is_empty_value(need) else 0

    # Company Mentioned - 10 points
    company = str(lead.get("companyName", "")).strip()
    company_score = 10 if company and not is_empty_value(company) else 0

    # Location Mentioned - 5 points
    loc = str(lead.get("location", "")).strip()
    location_score = 5 if loc and not is_empty_value(loc) else 0

    # Author Identified - 10 points
    author = str(lead.get("authorName", "")).strip()
    author_score = 10 if author and not is_empty_value(author) else 0

    total_score = intent_score + service_score + need_score + company_score + location_score + author_score

    # Force Category to "Low Intent" if intent is explicitly None/Low, or if intent type is General Discussion
    bi = str(buying_intent).strip().lower()
    it = str(intent_type).strip().lower()
    
    if bi in ["none", "low"] or it in ["general discussion", "none"]:
        category = "Low Intent"
        total_score = min(total_score, 35)  # Cap the score to reflect lack of true buying intent
    else:
        if total_score >= 70:
            category = "High Intent"
        elif total_score >= 40:
            category = "Medium Intent"
        else:
            category = "Low Intent"

    lead["leadScore"] = total_score
    lead["leadCategory"] = category
    return lead

def validate_author_name(author: str, platform: str = None) -> str:
    if not author or is_empty_value(author):
        return "Unknown"
    
    author_clean = str(author).strip()
    
    # 1. Reject names with question marks
    if "?" in author_clean:
        return "Unknown"
        
    # 2. Reject names with more than 3 words (relaxed to 6 words for facebook and 15 for google_maps to support business names)
    max_words = 6 if platform == "facebook" else (15 if platform == "google_maps" else 3)
    if len(author_clean.split()) > max_words:
        return "Unknown"
        
    # 3. Reject names containing specific phrases (case-insensitive)
    lower_author = author_clean.lower()
    reject_phrases = [
        "looking for", "need", "wanted", "hiring", 
        "seeking", "requirement", "opportunity"
    ]
    for phrase in reject_phrases:
        if phrase in lower_author:
            return "Unknown"
            
    return author_clean

def validate_company_name(company: str) -> str:
    if not company or is_empty_value(company):
        return "Not Specified"
    
    company_clean = str(company).strip()
    
    # 1. Reject names with more than 4 words
    if len(company_clean.split()) > 4:
        return "Not Specified"
        
    # 2. Reject names containing specific phrases (case-insensitive)
    lower_company = company_company = company_clean.lower()
    reject_phrases = [
        "looking for", "need", "wanted", "hiring", 
        "seeking", "requirement", "opportunity"
    ]
    for phrase in reject_phrases:
        if phrase in lower_company:
            return "Not Specified"
            
    return company_clean

