import logging
from fastapi import FastAPI
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

from starlette.middleware.base import BaseHTTPMiddleware
from app.services.activity_service import ActivityService
from app.core.security import decode_access_token

class ActivityLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        method = request.method
        path = request.url.path
        
        response = await call_next(request)
        
        # Log successful write/modify operations
        if response.status_code < 400 and method in ["POST", "PUT", "DELETE", "PATCH"]:
            try:
                # Resolve User ID from Authorization token
                user_id = "system"
                auth_header = request.headers.get("authorization")
                if auth_header and auth_header.startswith("Bearer "):
                    token = auth_header.split(" ")[1]
                    payload = decode_access_token(token)
                    if payload:
                        user_id = payload.get("sub", "system")
                        
                # Match request path to generate a readable action description
                action = None
                
                # User App events
                if "/api/auth/signup" in path:
                    action = "Registered Account"
                elif "/api/auth/forgot-password" in path:
                    action = "Requested Password Reset"
                elif "/api/auth/reset-password" in path:
                    action = "Completed Password Reset"
                elif "/api/users/profile" in path:
                    action = "Updated Profile Details"
                elif "/api/users/onboarding" in path:
                    action = "Completed Onboarding Setup"
                elif "/api/search" in path:
                    action = "Scraped Google Maps Leads"
                elif "/api/tenders/sync" in path:
                    action = "Synced Government Tenders"
                    
                # Admin Console events
                elif "/api/admin/create-admin" in path:
                    action = "Registered New Admin"
                elif "/api/admin/users/" in path:
                    if "/role" in path:
                        action = "Updated User Role"
                    elif "/credits" in path:
                        action = "Adjusted User Credits"
                    elif "/status" in path:
                        action = "Updated User Status"
                    elif "/password" in path:
                        action = "Changed User Password"
                    elif "/generate-password" in path:
                        action = "Generated User Password"
                    elif method == "DELETE":
                        action = "Deleted User Account"
                    else:
                        action = f"Modified User ({method})"
                elif "/api/admin/plans" in path:
                    action = "Modified Billing Plan Tiers"
                elif "/api/sync-sheets" in path:
                    action = "Synced Leads to Google Sheets"
                elif "/api/leads/bulk-delete" in path:
                    action = "Bulk Deleted Scraped Leads"
                    
                if action:
                    ActivityService.log(user_id, action, request)
            except Exception as e:
                print(f"[Activity Logging Error]: {e}")
                
        return response

app.add_middleware(ActivityLoggingMiddleware)

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
from app.api import auth, users, dashboard, maps, businesses, leads, pipeline, ai, enrichment, credits, subscription, integrations, webhooks, legacy_router, admin

app.include_router(legacy_router.router, prefix="", tags=["Legacy Compatibility"])
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
app.include_router(admin.router, prefix=f"{settings.API_PREFIX}/admin", tags=["Admin"])

