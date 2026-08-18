import os
import requests
import json

def get_apify_config():
    config_path = "config.json"
    default_config = {
        "apify": {
            "enabled": True,
            "actors": {
                "linkedin": "heidi/linkedin-posts-scraper",
                "twitter": "apify/twitter-scraper",
                "facebook": "apify/facebook-groups-scraper",
                "reddit": "apify/reddit-scraper"
            }
        }
    }
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                user_config = json.load(f)
                if "apify" in user_config:
                    # Update nested dict safely
                    if "actors" in user_config["apify"]:
                        default_config["apify"]["actors"].update(user_config["apify"]["actors"])
                    if "enabled" in user_config["apify"]:
                        default_config["apify"]["enabled"] = user_config["apify"]["enabled"]
        except Exception as e:
            print(f"[Apify Service] Error loading config.json: {e}")
    return default_config["apify"]

def scrape_apify_leads(platform: str, keyword: str, limit: int = 10) -> list:
    """
    Calls an Apify Actor synchronously for the given platform and keyword,
    and returns a normalized list of leads: [{'title': ..., 'snippet': ..., 'link': ...}]
    """
    token = os.getenv("APIFY_API_TOKEN") or ""
    if not token or not token.strip():
        print("[Apify Service] APIFY_API_TOKEN not found in environment. Skipping Apify.")
        return None

    config = get_apify_config()
    if not config.get("enabled", True):
        print("[Apify Service] Apify is disabled in config.json. Skipping Apify.")
        return None

    platform = platform.lower().strip()
    actors = config.get("actors", {})
    actor_id = actors.get(platform)

    if not actor_id:
        print(f"[Apify Service] No actor configured for platform: '{platform}'. Skipping Apify.")
        return None

    # Apify API requires the format username~actor-name (separated by tilde) in URL paths
    actor_id = actor_id.replace("/", "~")

    # Determine input payload format based on the platform / actor
    payload = {}
    if "linkedin" in platform:
        payload = {
            "searchQueries": [keyword],
            "maxPosts": limit
        }
    elif "twitter" in platform or "x" in platform:
        payload = {
            "searchTerms": [keyword],
            "maxItems": limit
        }
    elif "facebook" in platform:
        payload = {
            "searchQueries": [keyword],
            "resultsLimit": limit
        }
    elif "reddit" in platform:
        payload = {
            "queries": [keyword],
            "maxItems": limit
        }
    else:
        # Generic fallback payload structure
        payload = {
            "queries": [keyword],
            "limit": limit,
            "maxItems": limit
        }

    # Use the synchronous API run endpoint: wait and return dataset items in one request
    # Max wait time is set to 60 seconds (60000ms) to prevent hanging, or default 300s
    url = f"https://api.apify.com/v2/acts/{actor_id}/run-sync-get-dataset-items?token={token}&timeout=60"
    
    print(f"[Apify Service] Launching Actor '{actor_id}' for query: {keyword!r} (Limit: {limit})...")
    
    try:
        response = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=65)
        
        if response.status_code == 201 or response.status_code == 200:
            raw_items = response.json()
            if not isinstance(raw_items, list):
                print(f"[Apify Service] Actor response is not a list: {raw_items}")
                return []
            
            normalized_results = []
            for item in raw_items:
                # Safe getter mappings for various scraper models
                
                # 1. Text / Snippet extraction
                text = (
                    item.get("text") or 
                    item.get("fullText") or 
                    item.get("message") or 
                    item.get("content") or 
                    item.get("description") or 
                    item.get("selftext") or 
                    ""
                )
                
                # 2. URL / Link extraction
                link = (
                    item.get("linkedinUrl") or 
                    item.get("postUrl") or 
                    item.get("url") or 
                    item.get("link") or 
                    item.get("shareLinkedinUrl") or
                    item.get("tweetUrl") or
                    item.get("postLinkedinUrl") or
                    item.get("facebookUrl") or
                    ""
                )
                if not link and item.get("id"):
                    # Construct link from ID as safety
                    if "twitter" in platform:
                        link = f"https://twitter.com/x/status/{item.get('id')}"
                    elif "reddit" in platform:
                        link = f"https://reddit.com/{item.get('id')}"

                # 3. Author Name
                author = (
                    item.get("authorName") or 
                    item.get("username") or 
                    item.get("author") or 
                    item.get("user", {}).get("name") or 
                    item.get("author", {}).get("name") or 
                    "Social Lead"
                )
                if isinstance(author, dict):
                    author = author.get("name") or author.get("username") or "Social Lead"
                
                # If both link and snippet are empty, ignore this record
                if not link and not text:
                    continue
                
                title = f"{author} on {platform.capitalize()}"
                
                normalized_results.append({
                    "title": title[:100],
                    "snippet": text,
                    "link": link
                })
            
            print(f"[Apify Service] Successfully scraped and mapped {len(normalized_results)} leads.")
            return normalized_results
            
        elif response.status_code == 402:
            print(f"[Apify Service] Error 402: Apify subscription/credits exceeded. Falling back to Serper.")
            return None
        elif response.status_code == 401:
            print(f"[Apify Service] Error 401: Invalid API token. Falling back to Serper.")
            return None
        else:
            print(f"[Apify Service] Actor run returned status code {response.status_code}: {response.text}")
            return None
            
    except requests.exceptions.Timeout:
        print(f"[Apify Service] Request timed out after 65s. Falling back to Serper.")
        return None
    except Exception as e:
        print(f"[Apify Service] Exception occurred calling Apify: {e}. Falling back to Serper.")
        return None
