import sys
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(errors="replace")
        sys.stderr.reconfigure(errors="replace")
    except Exception:
        pass

import logging
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.core.database import db_manager

# Configure Logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mapflow_ai.main")

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    openapi_url=f"{settings.API_PREFIX}/openapi.json"
)

# CORS Setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def log_headers_middleware(request: Request, call_next):
    if request.url.path.startswith("/api/"):
        auth_header = request.headers.get("Authorization")
        print(f"[AUTH LOG] Path: {request.url.path} | Authorization: {auth_header}")
    return await call_next(request)

@app.on_event("startup")
async def startup_event():
    logger.info("Initializing MapFlow AI Backend Services...")
    db_manager.connect()

@app.get("/")
async def root():
    return {
        "success": True,
        "product": "MapFlow AI",
        "version": settings.VERSION,
        "db_mode": "JSON_FALLBACK" if db_manager.use_json_fallback else "MONGODB"
    }

# Import and Register API Routers
from app.api import auth, users, dashboard, maps, businesses, leads, pipeline, ai, enrichment, credits, subscription, integrations, webhooks

app.include_router(auth.router, prefix=f"{settings.API_PREFIX}/auth", tags=["Auth"])
app.include_router(users.router, prefix=f"{settings.API_PREFIX}/users", tags=["Users"])
app.include_router(dashboard.router, prefix=f"{settings.API_PREFIX}/dashboard", tags=["Dashboard"])
app.include_router(maps.router, prefix=f"{settings.API_PREFIX}/maps", tags=["Google Maps Search"])
app.include_router(businesses.router, prefix=f"{settings.API_PREFIX}/businesses", tags=["Businesses"])
app.include_router(leads.router, prefix=f"{settings.API_PREFIX}/leads", tags=["Leads"])
app.include_router(pipeline.router, prefix=f"{settings.API_PREFIX}/pipeline", tags=["CRM Pipeline"])
app.include_router(ai.router, prefix=f"{settings.API_PREFIX}/ai", tags=["AI Engine"])
app.include_router(enrichment.router, prefix=f"{settings.API_PREFIX}/enrichment", tags=["Enrichment"])
app.include_router(credits.router, prefix=f"{settings.API_PREFIX}/credits", tags=["Credits"])
app.include_router(subscription.router, prefix=f"{settings.API_PREFIX}/subscription", tags=["Subscription"])
app.include_router(integrations.router, prefix=f"{settings.API_PREFIX}/integrations", tags=["Integrations"])
app.include_router(webhooks.router, prefix=f"{settings.API_PREFIX}/webhooks", tags=["Webhooks"])

# Register exact POST /api/enrich-team endpoint requested
from app.api.enrichment import enrich_team_route
app.post("/api/enrich-team", tags=["Enrichment"])(enrich_team_route)

