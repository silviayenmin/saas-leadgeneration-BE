import sys
import os
import uuid

# Add parent directory to sys.path to allow importing app
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import db_manager
from app.core.security import get_password_hash

def main():
    db_manager.connect()

    email = "admin@mapflow.ai"
    password = "admin123"

    # Query if exists
    coll = db_manager.get_collection("users")
    if coll is not None:
        existing = coll.find_one({"email": email})
    else:
        existing = db_manager.json_db.find_one("users", {"email": email})

    if existing:
        print(f"User with email '{email}' already exists.")
        return

    user_id = str(uuid.uuid4())
    import datetime
    now_iso = datetime.datetime.utcnow().isoformat()
    new_user = {
        "id": user_id,
        "fullName": "Admin User",
        "email": email,
        "passwordHash": get_password_hash(password),
        "isVerified": True,
        "otpCode": None,
        "role": "admin",
        "createdAt": now_iso,
        "onboardingCompleted": True
    }

    new_sub = {
        "userId": user_id,
        "plan": "AGENCY_PRO",
        "creditLimit": 3000,
        "creditsUsed": 150,
        "resetDate": "2026-09-20",
        "updatedAt": now_iso
    }

    if coll is not None:
        coll.insert_one(new_user)
        db_manager.get_collection("subscriptions").insert_one(new_sub)
    else:
        db_manager.json_db.insert_one("users", new_user)
        db_manager.json_db.insert_one("subscriptions", new_sub)

    print(f"Created Admin account successfully!")
    print(f"Email: {email}")
    print(f"Password: {password}")
    print(f"Role: admin")

if __name__ == "__main__":
    main()
