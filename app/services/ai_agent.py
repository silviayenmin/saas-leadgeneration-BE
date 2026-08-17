import os
import json
import httpx

# Resolve config.json path
config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "config.json")
if not os.path.exists(config_path):
    config_path = "config.json"

def load_config() -> dict:
    if os.path.exists(config_path):
        try:
            with open(config_path, "r") as f:
                return json.load(f)
        except Exception as e:
            print(f"[AI Agent Config] Failed to load config.json: {e}")
    return {}

class MockCompletions:
    def create(self, messages, response_format=None, temperature=0.1):
        config = load_config()
        active_provider_name = config.get("active_provider", "groq")
        providers = config.get("providers", {})
        provider_config = providers.get(active_provider_name, {})
        
        provider_type = provider_config.get("provider_type", "groq").lower()
        model = provider_config.get("model", "llama-3.3-70b-versatile")
        base_url = provider_config.get("base_url")
        config_temp = provider_config.get("temperature", temperature)

        print(f"[AI Agent] Routing request to provider '{active_provider_name}' (type: {provider_type}, model: {model})")

        headers = {}
        payload = {}

        if provider_type == "groq":
            url = "https://api.groq.com/openai/v1/chat/completions"
            api_key = os.getenv("GROQ_API_KEY")
            if not api_key:
                raise Exception("GROQ_API_KEY environment variable is not set.")
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": model,
                "messages": messages,
                "temperature": config_temp,
                "max_tokens": 4096
            }
            if response_format:
                payload["response_format"] = response_format

        elif provider_type == "openai":
            url = "https://api.openai.com/v1/chat/completions"
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise Exception("OPENAI_API_KEY environment variable is not set.")
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": model,
                "messages": messages,
                "temperature": config_temp,
                "max_tokens": 4096
            }
            if response_format:
                payload["response_format"] = response_format

        elif provider_type == "ollama":
            b_url = base_url or "http://localhost:11434"
            url = f"{b_url.rstrip('/')}/v1/chat/completions"
            headers = {
                "Content-Type": "application/json"
            }
            payload = {
                "model": model,
                "messages": messages,
                "temperature": config_temp,
                "max_tokens": 4096
            }
            if response_format:
                payload["response_format"] = response_format

        elif provider_type == "gemini":
            api_key = os.getenv("GEMINI_API_KEY")
            if not api_key:
                raise Exception("GEMINI_API_KEY environment variable is not set.")
            
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            headers = {
                "Content-Type": "application/json"
            }
            contents = []
            for m in messages:
                role = "model" if m["role"] == "assistant" else "user"
                contents.append({
                    "role": role,
                    "parts": [{"text": m["content"]}]
                })
            payload = {
                "contents": contents
            }
            
            with httpx.Client(timeout=30.0) as client:
                res = client.post(url, headers=headers, json=payload)
                if res.status_code == 200:
                    data = res.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        text = candidates[0]["content"]["parts"][0]["text"]
                        
                        class Choice:
                            class Message:
                                def __init__(self, c):
                                    self.content = c
                            def __init__(self, c):
                                self.message = self.Message(c)
                        class Response:
                            def __init__(self, c):
                                self.choices = [Choice(c)]
                        return Response(text)
                    else:
                        raise Exception(f"Gemini API returned no candidates: {res.text}")
                else:
                    raise Exception(f"Gemini API Error ({res.status_code}): {res.text}")

        elif provider_type == "anthropic":
            url = "https://api.anthropic.com/v1/messages"
            api_key = os.getenv("ANTHROPIC_API_KEY")
            if not api_key:
                raise Exception("ANTHROPIC_API_KEY environment variable is not set.")
            headers = {
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json"
            }
            system_msg = ""
            user_messages = []
            for m in messages:
                if m["role"] == "system":
                    system_msg = m["content"]
                else:
                    user_messages.append({
                        "role": m["role"],
                        "content": m["content"]
                    })
            payload = {
                "model": model,
                "messages": user_messages,
                "max_tokens": 4096,
                "temperature": config_temp
            }
            if system_msg:
                payload["system"] = system_msg
                
            with httpx.Client(timeout=30.0) as client:
                res = client.post(url, headers=headers, json=payload)
                if res.status_code == 200:
                    data = res.json()
                    text = data["content"][0]["text"]
                    
                    class Choice:
                        class Message:
                            def __init__(self, c):
                                self.content = c
                        def __init__(self, c):
                            self.message = self.Message(c)
                    class Response:
                        def __init__(self, c):
                            self.choices = [Choice(c)]
                    return Response(text)
                else:
                    raise Exception(f"Anthropic API Error ({res.status_code}): {res.text}")

        # Call OpenAI-compatible REST endpoint (Groq, OpenAI, Ollama)
        with httpx.Client(timeout=30.0) as client:
            try:
                res = client.post(url, headers=headers, json=payload)
                if res.status_code == 200:
                    data = res.json()
                    content = data["choices"][0]["message"]["content"]
                    
                    class Choice:
                        class Message:
                            def __init__(self, c):
                                self.content = c
                        def __init__(self, c):
                            self.message = self.Message(c)
                    class Response:
                        def __init__(self, c):
                            self.choices = [Choice(c)]
                    return Response(content)
                else:
                    # Self-healing fallback for Groq
                    if provider_type == "groq" and res.status_code in (404, 400) and model == "llama-3.3-70b-versatile":
                        print("[AI Agent] Llama 3.3-70b failed. Retrying with fallback openai/gpt-oss-20b...")
                        payload["model"] = "openai/gpt-oss-20b"
                        res2 = client.post(url, headers=headers, json=payload)
                        if res2.status_code == 200:
                            data2 = res2.json()
                            content2 = data2["choices"][0]["message"]["content"]
                            class Choice:
                                class Message:
                                    def __init__(self, c):
                                        self.content = c
                                def __init__(self, c):
                                    self.message = self.Message(c)
                            class Response:
                                def __init__(self, c):
                                    self.choices = [Choice(c)]
                            return Response(content2)
                    raise Exception(f"API Error ({res.status_code}): {res.text}")
            except Exception as e:
                # Catch-all fallback for Groq
                if provider_type == "groq" and model != "openai/gpt-oss-20b":
                    print(f"[AI Agent] Provider failed: {e}. Attempting direct fallback to openai/gpt-oss-20b...")
                    payload["model"] = "openai/gpt-oss-20b"
                    try:
                        res2 = client.post(url, headers=headers, json=payload)
                        if res2.status_code == 200:
                            data2 = res2.json()
                            content2 = data2["choices"][0]["message"]["content"]
                            class Choice:
                                class Message:
                                    def __init__(self, c):
                                        self.content = c
                                def __init__(self, c):
                                    self.message = self.Message(c)
                            class Response:
                                def __init__(self, c):
                                    self.choices = [Choice(c)]
                            return Response(content2)
                        else:
                            print(f"[AI Agent Fallback] Failed with status {res2.status_code}: {res2.text}")
                    except Exception as fb_e:
                        print(f"[AI Agent Fallback] Exception: {fb_e}")
                raise e

class MockChat:
    def __init__(self):
        self.completions = MockCompletions()

class MockClient:
    def __init__(self):
        self.chat = MockChat()

client = MockClient()
