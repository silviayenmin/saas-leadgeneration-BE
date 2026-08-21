import uuid
from datetime import datetime
from fastapi import Request
from app.core.database import db_manager

class ActivityService:
    @staticmethod
    def get_client_info(request: Request) -> tuple:
        """
        Extracts clean IP address and Device Name from the request headers.
        """
        if not request:
            return "127.0.0.1", "System"
            
        # Get IP
        ip = "127.0.0.1"
        if request.client:
            ip = request.client.host
        # Check X-Forwarded-For header if behind reverse proxy
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            ip = forwarded_for.split(",")[0].strip()

        # Parse user-agent
        ua_string = request.headers.get("user-agent", "Unknown Device")
        device = "Unknown Browser"
        
        # Simple parser for browser name & OS
        ua_lower = ua_string.lower()
        
        # Detect OS
        os_name = "Unknown OS"
        if "windows" in ua_lower:
            os_name = "Windows"
        elif "macintosh" in ua_lower or "mac os" in ua_lower:
            os_name = "macOS"
        elif "linux" in ua_lower:
            os_name = "Linux"
        elif "iphone" in ua_lower or "ipad" in ua_lower:
            os_name = "iOS"
        elif "android" in ua_lower:
            os_name = "Android"
            
        # Detect Browser
        browser_name = "Unknown Browser"
        if "chrome" in ua_lower or "chromium" in ua_lower:
            # Chrome UA also contains Safari, so check chrome first
            browser_name = "Chrome"
        elif "firefox" in ua_lower:
            browser_name = "Firefox"
        elif "safari" in ua_lower:
            browser_name = "Safari"
        elif "edge" in ua_lower:
            browser_name = "Edge"
            
        device = f"{browser_name} - {os_name}" if browser_name != "Unknown Browser" else ua_string[:30]
        return ip, device

    @staticmethod
    def log(user_id: str, action: str, request: Request = None):
        """
        Logs a user or admin event into the activity_logs database collection.
        """
        ip, device = ActivityService.get_client_info(request)
        
        # Retrieve user details from database
        coll_users = db_manager.get_collection("users")
        if coll_users is not None:
            user = coll_users.find_one({"id": user_id})
        else:
            user = db_manager.json_db.find_one("users", {"id": user_id})
            
        user_name = "System"
        user_email = "system@mapflow.ai"
        
        if user:
            user_name = user.get("fullName") or user.get("name") or "User"
            user_email = user.get("email") or "user@mapflow.ai"
        elif user_id == "admin":
            user_name = "Super Admin"
            user_email = "admin@mapflow.ai"
            
        log_entry = {
            "id": str(uuid.uuid4()),
            "userId": user_id,
            "userName": user_name,
            "userEmail": user_email,
            "action": action,
            "ipAddress": ip,
            "device": device,
            # Format as DD/MM/YYYY, HH:MM:SS to align with frontend parsing expectations
            "timestamp": datetime.now().strftime("%d/%m/%Y, %H:%M:%S")
        }
        
        coll_logs = db_manager.get_collection("activity_logs")
        if coll_logs is not None:
            coll_logs.insert_one(log_entry)
        else:
            db_manager.json_db.insert_one("activity_logs", log_entry)
