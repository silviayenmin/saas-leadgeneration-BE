# MapFlow AI — Backend Engine

AI-Powered Google Maps B2B Local Business Lead Generation & Outreach SaaS Platform Backend.

## Features & Tech Stack
- **Framework**: FastAPI (Python 3.10+)
- **Database**: MongoDB with automatic JSON file fallback (`database.db`, `login.json`) for local development.
- **Scraping & Crawling**: Playwright + Chromium (Google Maps) & BeautifulSoup4 + lxml (Website Intelligence).
- **AI Service**: Groq Llama-3.3-70B primary & Ollama Llama-3.1 8B fallback.
- **Credit & Billing System**: Atomic credit checking, tracking, deduction, and plan enforcement.

## Getting Started

```bash
# Install dependencies
pip install -r requirements.txt

# Install Playwright browser binaries
playwright install chromium

# Run development ASGI server
uvicorn app.main:app --reload --port 8000
```
