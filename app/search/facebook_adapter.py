from app.services.serper import search_leads
from app.services.apify import scrape_apify_leads

class FacebookAdapter:
    def __init__(self):
        self.platform_name = "facebook"
        
    def search(self, keyword: str, timeframe: str = "qdr:m3", match_type: str = "partial", location: str = None, industry: str = None, api_key: str = None, limit: int = 10, raw_keyword: str = None) -> list:
        # Try Apify search first
        try:
            search_term = raw_keyword if raw_keyword else keyword
            print(f"[FacebookAdapter] Trying Apify search for keyword: {search_term}")
            apify_results = scrape_apify_leads("facebook", search_term, limit=limit)
            if apify_results is not None:
                return apify_results
            print("[FacebookAdapter] Apify returned None or is not available. Falling back to Serper.")
        except Exception as ae:
            print(f"[FacebookAdapter] Apify search failed: {ae}. Falling back to Serper.")

        # Fallback to Serper search
        q_parts = []
        if match_type == "exact":
            q_parts.append(f'"{keyword}"')
        else:
            q_parts.append(keyword)
            
        if location and location.strip():
            q_parts.append(location.strip())
            
        if industry and industry.strip():
            q_parts.append(f'"{industry.strip()}"')
            
        query = f'site:facebook.com {" ".join(q_parts)}'
            
        print(f"[FacebookAdapter] Searching query via Serper fallback: {query}")
        try:
            serper_results = search_leads(query, tbs=timeframe, api_key=api_key, num=limit)
            return [r for r in serper_results if "facebook.com" in (r.get("link") or "").lower()]
        except Exception as e:
            print(f"[FacebookAdapter] Serper Fallback Error: {e}")
            return []
