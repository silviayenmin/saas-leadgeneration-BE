import requests
import os

def search_leads(query, tbs=None, api_key=None, num=None):
    payload = {
        "q": query
    }
    if tbs:
        payload["tbs"] = tbs
    if num:
        payload["num"] = min(max(int(num), 1), 100)

    serper_key = api_key if (api_key and api_key.strip()) else os.getenv("SERPER_API_KEY") or ""
    print(f"[Serper] Requesting query: {query!r} | Key: {serper_key[:5]}...{serper_key[-5:] if len(serper_key) > 5 else ''} (len: {len(serper_key)})")

    try:
        response = requests.post(
            "https://google.serper.dev/search",
            headers={
                "X-API-KEY": serper_key,
                "Content-Type": "application/json"
            },
            json=payload,
            timeout=15
        )
        if response.status_code == 200:
            results = response.json().get("organic", [])
            requested_num = payload.get("num", 10)
            if requested_num > 10 and len(results) >= 10:
                print(f"[Serper] Got {len(results)} results on first page, but requested {requested_num}. Paginating...")
                combined_results = list(results)
                pages_needed = (requested_num + 9) // 10
                # We already got page 1 results, so start from page 2
                for page in range(2, pages_needed + 1):
                    payload_page = payload.copy()
                    payload_page["num"] = 10
                    payload_page["page"] = page
                    try:
                        response_page = requests.post(
                            "https://google.serper.dev/search",
                            headers={
                                "X-API-KEY": serper_key,
                                "Content-Type": "application/json"
                            },
                            json=payload_page,
                            timeout=15
                        )
                        if response_page.status_code == 200:
                            page_results = response_page.json().get("organic", [])
                            if not page_results:
                                break
                            combined_results.extend(page_results)
                            if len(page_results) < 10:
                                break
                        else:
                            print(f"[Serper] Paginated request for page {page} failed with status {response_page.status_code}")
                            break
                    except Exception as fe:
                        print(f"[Serper] Paginated page {page} exception: {fe}")
                        break
                return combined_results[:requested_num]
            return results
        elif response.status_code == 400 and "Query pattern not allowed" in response.text:
            print(f"[Serper] Free account query pattern block detected for query {query!r}.")
            
            # Step 1 Fallback: If num > 10, try fetching multiple pages of 10 items
            if payload.get("num", 10) > 10:
                requested_num = payload.get("num")
                print(f"[Serper] Fallback Step 1: Paginating query {query!r} to fetch up to {requested_num} results (10 per page)...")
                combined_results = []
                pages_needed = (requested_num + 9) // 10
                for page in range(1, pages_needed + 1):
                    payload_page = payload.copy()
                    payload_page["num"] = 10
                    payload_page["page"] = page
                    try:
                        response_page = requests.post(
                            "https://google.serper.dev/search",
                            headers={
                                "X-API-KEY": serper_key,
                                "Content-Type": "application/json"
                            },
                            json=payload_page,
                            timeout=15
                        )
                        if response_page.status_code == 200:
                            page_results = response_page.json().get("organic", [])
                            if not page_results:
                                break
                            combined_results.extend(page_results)
                        else:
                            print(f"[Serper] Paginated fallback request for page {page} failed with status {response_page.status_code}")
                            break
                    except Exception as fe:
                        print(f"[Serper] Paginated fallback page {page} exception: {fe}")
                        break
                if combined_results:
                    return combined_results[:requested_num]
            
            # Step 2 Fallback: Try stripping site: and resetting num to None (or paginating if num > 10)
            if "site:" in query:
                fallback_query = query.replace("site:", "")
                print(f"[Serper] Fallback Step 2: Retrying without site: {fallback_query!r}...")
                if payload.get("num", 10) > 10:
                    requested_num = payload.get("num")
                    combined_results = []
                    pages_needed = (requested_num + 9) // 10
                    for page in range(1, pages_needed + 1):
                        payload_page = payload.copy()
                        payload_page["q"] = fallback_query
                        payload_page["num"] = 10
                        payload_page["page"] = page
                        try:
                            response_page = requests.post(
                                "https://google.serper.dev/search",
                                headers={
                                    "X-API-KEY": serper_key,
                                    "Content-Type": "application/json"
                                },
                                json=payload_page,
                                timeout=15
                            )
                            if response_page.status_code == 200:
                                page_results = response_page.json().get("organic", [])
                                if not page_results:
                                    break
                                combined_results.extend(page_results)
                            else:
                                break
                        except Exception:
                            break
                    if combined_results:
                        return combined_results[:requested_num]
                else:
                    payload_fallback = payload.copy()
                    payload_fallback["q"] = fallback_query
                    payload_fallback.pop("num", None)
                    try:
                        response = requests.post(
                            "https://google.serper.dev/search",
                            headers={
                                "X-API-KEY": serper_key,
                                "Content-Type": "application/json"
                            },
                            json=payload_fallback,
                            timeout=15
                        )
                        if response.status_code == 200:
                            return response.json().get("organic", [])
                    except Exception as fe:
                        print(f"[Serper] Fallback Step 2 exception: {fe}")
                        
            print(f"[Serper] All fallbacks failed. API returned non-200 status code {response.status_code}: {response.text}")
            return []
        else:
            print(f"[Serper] API returned non-200 status code {response.status_code}: {response.text}")
            return []
    except Exception as e:
        print(f"[Serper] Error calling API: {e}")
        return []
