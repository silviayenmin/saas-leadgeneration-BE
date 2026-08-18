import urllib.request
import urllib.parse
import json
import datetime
from app.services.serper import search_leads

class FreelancerAdapter:
    def __init__(self):
        self.platform_name = "freelancer"

    def search(self, keyword: str, timeframe: str = None, match_type: str = "partial", location: str = None, industry: str = None, api_key: str = None, limit: int = 10, raw_keyword: str = None) -> list:
        search_term = raw_keyword if raw_keyword else keyword
        print(f"[FreelancerAdapter] Fetching Freelancer.com active projects for keyword: '{search_term}'")
        
        encoded_query = urllib.parse.quote(search_term)
        api_url = f"https://www.freelancer.com/api/projects/0.1/projects/active/?query={encoded_query}&limit={limit}"
        
        results = []
        try:
            req = urllib.request.Request(
                api_url, 
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode('utf-8'))
                
            if data.get("status") == "success" and "result" in data:
                projects = data["result"].get("projects", [])
                
                # Filter out generic stop words to find the niche search terms
                generic_words = {"project", "projects", "job", "jobs", "work", "works", "freelancer", "freelance", "contract", "developer", "development", "designer", "design", "hiring", "hire", "need", "looking", "for", "service", "services", "agency"}
                query_words = [w.strip() for w in search_term.lower().split() if w.strip()]
                specific_words = [w for w in query_words if w not in generic_words]

                for proj in projects:
                    if len(results) >= limit:
                        break
                    title_text = proj.get("title") or "No Title"
                    desc_text = proj.get("description") or ""
                    
                    # Apply specific words filtering to remove loose OR API matches
                    if specific_words:
                        text_to_match = (title_text + " " + desc_text).lower()
                        if not any(sw in text_to_match for sw in specific_words):
                            continue
                    
                    # Construct project link using the seo_url slug
                    seo_url = proj.get("seo_url")
                    if seo_url:
                        link_text = f"https://www.freelancer.com/projects/{seo_url}"
                    else:
                        proj_id = proj.get("id")
                        link_text = f"https://www.freelancer.com/projects/{proj_id}" if proj_id else ""
                    
                    # Convert submitdate timestamp to string
                    submit_date = proj.get("submitdate")
                    pub_date_str = ""
                    if submit_date:
                        try:
                            pub_date_str = datetime.datetime.utcfromtimestamp(submit_date).isoformat() + "Z"
                        except Exception:
                            pass
                            
                    results.append({
                        "title": title_text,
                        "snippet": desc_text,
                        "link": link_text,
                        "pubDate": pub_date_str
                    })
        except Exception as e:
            print(f"[FreelancerAdapter] Error parsing Freelancer.com API: {e}")
            
        # Fallback to Serper Google Search if Freelancer API returned 0 matching results or failed
        if not results:
            print(f"[FreelancerAdapter] API returned 0 results or failed. Falling back to Serper search.")
            try:
                q_parts = []
                if match_type == "exact":
                    q_parts.append(f'"{search_term}"')
                else:
                    q_parts.append(search_term)
                
                if location and location.strip():
                    q_parts.append(location.strip())
                    
                if industry and industry.strip():
                    q_parts.append(f'"{industry.strip()}"')
                    
                query = f'site:freelancer.com/projects {" ".join(q_parts)}'
                print(f"[FreelancerAdapter] Searching query via Serper: {query}")
                serper_results = search_leads(query, tbs=timeframe, api_key=api_key, num=limit)
                
                # If timeframe filter yielded 0 results, retry without timeframe filter
                if not serper_results and timeframe:
                    print(f"[FreelancerAdapter] Serper returned 0 results with timeframe '{timeframe}'. Retrying without timeframe filter.")
                    serper_results = search_leads(query, tbs=None, api_key=api_key, num=limit)

                for r in serper_results:
                    link_text = r.get("link") or ""
                    if "freelancer.com" not in link_text.lower():
                        continue
                    title_text = r.get("title") or "No Title"
                    snippet_text = r.get("snippet") or ""

                    # Apply specific words filtering to remove loose OR Google matches
                    if specific_words:
                        text_to_match = (title_text + " " + snippet_text).lower()
                        if not any(sw in text_to_match for sw in specific_words):
                            continue

                    if title_text.startswith("http://") or title_text.startswith("https://") or "freelancer.com/projects" in title_text.lower():
                        title_text = "Freelancer Project Opportunity"
                    else:
                        for suffix in [" - Freelancer", " | Freelancer", " on Freelancer"]:
                            if title_text.endswith(suffix):
                                title_text = title_text[:-len(suffix)].strip()
                    results.append({
                        "title": title_text,
                        "snippet": snippet_text,
                        "link": link_text,
                        "pubDate": r.get("date") or ""
                    })
            except Exception as se:
                print(f"[FreelancerAdapter] Serper fallback failed: {se}")

        return results
