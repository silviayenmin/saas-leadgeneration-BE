import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import html
import re
from app.services.serper import search_leads

class UpworkAdapter:
    def __init__(self):
        self.platform_name = "upwork"

    def search(self, keyword: str, timeframe: str = None, match_type: str = "partial", location: str = None, industry: str = None, api_key: str = None, limit: int = 10, raw_keyword: str = None) -> list:
        search_term = raw_keyword if raw_keyword else keyword
        print(f"[UpworkAdapter] Fetching Upwork RSS for keyword: '{search_term}'")
        
        encoded_query = urllib.parse.quote_plus(search_term)
        rss_url = f"https://www.upwork.com/ab/feed/jobs/rss?q={encoded_query}"
        
        results = []
        try:
            req = urllib.request.Request(
                rss_url, 
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                xml_data = response.read()
                
            root = ET.fromstring(xml_data)
            items = root.findall('.//item')
            
            for item in items[:limit]:
                title = item.find('title')
                link = item.find('link')
                description = item.find('description')
                
                title_text = title.text if title is not None else "No Title"
                link_text = link.text if link is not None else ""
                
                desc_text = ""
                if description is not None and description.text:
                    # Clean up html tags inside description
                    desc_text = html.unescape(description.text)
                    desc_text = re.sub(r'<[^>]*>', ' ', desc_text)
                    desc_text = re.sub(r'\s+', ' ', desc_text).strip()
                
                results.append({
                    "title": title_text,
                    "snippet": desc_text,
                    "link": link_text,
                    "pubDate": item.find('pubDate').text if item.find('pubDate') is not None else ""
                })
        except Exception as e:
            print(f"[UpworkAdapter] Error parsing Upwork RSS: {e}. Falling back to Serper Google search.")
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
                    
                query = f'site:upwork.com/freelance-jobs {" ".join(q_parts)}'
                print(f"[UpworkAdapter] Searching query via Serper: {query}")
                serper_results = search_leads(query, tbs=timeframe, api_key=api_key, num=limit)
                
                # If timeframe filter yielded 0 results, retry without timeframe filter
                if not serper_results and timeframe:
                    print(f"[UpworkAdapter] Serper returned 0 results with timeframe '{timeframe}'. Retrying without timeframe filter.")
                    serper_results = search_leads(query, tbs=None, api_key=api_key, num=limit)

                for r in serper_results:
                    link_text = r.get("link") or ""
                    if "upwork.com" not in link_text.lower():
                        continue
                    title_text = r.get("title") or "No Title"
                    if title_text.startswith("http://") or title_text.startswith("https://") or "upwork.com/jobs" in title_text.lower() or "upwork.com/freelance-jobs" in title_text.lower():
                        title_text = "Upwork Project Opportunity"
                    else:
                        for suffix in [" - Upwork", " | Upwork", " on Upwork"]:
                            if title_text.endswith(suffix):
                                title_text = title_text[:-len(suffix)].strip()
                    results.append({
                        "title": title_text,
                        "snippet": r.get("snippet") or "",
                        "link": r.get("link") or "",
                        "pubDate": r.get("date") or ""
                    })
            except Exception as se:
                print(f"[UpworkAdapter] Serper fallback failed: {se}")
            
        # Filter results by specific keywords to guarantee relevance
        generic_words = {"project", "projects", "job", "jobs", "work", "works", "freelancer", "freelance", "contract", "developer", "development", "designer", "design", "hiring", "hire", "need", "looking", "for", "service", "services", "agency"}
        query_words = [w.strip() for w in search_term.lower().split() if w.strip()]
        specific_words = [w for w in query_words if w not in generic_words]
        
        if specific_words:
            filtered_results = []
            for r in results:
                text_to_match = (r.get("title", "") + " " + r.get("snippet", "")).lower()
                if any(sw in text_to_match for sw in specific_words):
                    filtered_results.append(r)
            return filtered_results
            
        return results
