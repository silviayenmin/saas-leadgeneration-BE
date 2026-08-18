import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import html
import re

class WeWorkRemotelyAdapter:
    def __init__(self):
        self.platform_name = "weworkremotely"

    def search(self, keyword: str, timeframe: str = None, match_type: str = "partial", location: str = None, industry: str = None, api_key: str = None, limit: int = 10, raw_keyword: str = None) -> list:
        search_term = raw_keyword if raw_keyword else keyword
        print(f"[WeWorkRemotelyAdapter] Fetching remote jobs matching keyword: '{search_term}'")
        
        rss_url = "https://weworkremotely.com/remote-jobs.rss"
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
            
            search_term_lower = search_term.lower()
            
            # Smart filtering: exact match first, then split core keyword search
            # Define common generic words to filter out if there are specific tech keywords
            stop_words = {"project", "projects", "job", "jobs", "developer", "designer", "contract", "remote", "hire", "hiring", "work", "need", "needed", "freelance", "freelancer", "brief", "briefs", "client", "clients", "program", "programming", "software", "development"}
            
            query_words = [w.strip() for w in search_term_lower.split() if w.strip()]
            core_words = [w for w in query_words if w not in stop_words]
            if not core_words:
                core_words = query_words
            
            for item in items:
                title = item.find('title')
                link = item.find('link')
                description = item.find('description')
                
                title_text = title.text if title is not None else "No Title"
                link_text = link.text if link is not None else ""
                
                desc_text = ""
                if description is not None and description.text:
                    desc_text = html.unescape(description.text)
                    desc_text = re.sub(r'<[^>]*>', ' ', desc_text)
                    desc_text = re.sub(r'\s+', ' ', desc_text).strip()
                
                # Match title and description
                title_lower = title_text.lower()
                desc_lower = desc_text.lower()
                
                # Match: check if exact phrase matches first, otherwise check if all core keywords match
                is_match = (search_term_lower in title_lower or search_term_lower in desc_lower)
                if not is_match and core_words:
                    is_match = all(w in title_lower or w in desc_lower for w in core_words)
                
                if is_match:
                    results.append({
                        "title": title_text,
                        "snippet": desc_text[:500] + ("..." if len(desc_text) > 500 else ""),
                        "link": link_text,
                        "pubDate": item.find('pubDate').text if item.find('pubDate') is not None else ""
                    })
                    
                    if len(results) >= limit:
                        break
        except Exception as e:
            print(f"[WeWorkRemotelyAdapter] Error parsing WeWorkRemotely RSS: {e}")
            
        return results
