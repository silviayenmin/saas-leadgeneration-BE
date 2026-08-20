from fastapi import APIRouter, Depends, HTTPException, status
from typing import Dict, Any, List, Optional
from pydantic import BaseModel
from app.core.security import get_current_admin_user
from app.core.database import db_manager

router = APIRouter()

# Schema for updating user role
class UpdateRoleRequest(BaseModel):
    role: str

# Schema for adjusting user credits
class AdjustCreditsRequest(BaseModel):
    creditLimit: int
    creditsUsed: int

@router.get("/stats")
def get_system_stats(admin_user: dict = Depends(get_current_admin_user)):
    # 1. Total Users
    coll_users = db_manager.get_collection("users")
    if coll_users is not None:
        users = list(coll_users.find({}))
    else:
        users = db_manager.json_db.find("users")
    total_users = len(users)

    # Load subscriptions for plan aggregation
    coll_subs = db_manager.get_collection("subscriptions")
    if coll_subs is not None:
        subs = list(coll_subs.find({}))
    else:
        subs = db_manager.json_db.find("subscriptions")

    # Map subs by userId
    subs_map = {sub.get("userId"): sub for sub in subs if "userId" in sub}
    users_map = {u.get("id"): u for u in users if "id" in u}

    # Aggregate plan tiers
    free_count = 0
    starter_count = 0
    agency_count = 0

    for u in users:
        u_id = u.get("id")
        user_sub = subs_map.get(u_id, {})
        plan = user_sub.get("plan", "FREE")
        if plan == "STARTER":
            starter_count += 1
        elif plan == "AGENCY_PRO":
            agency_count += 1
        else:
            free_count += 1

    # 2. Total Scans
    coll_scans = db_manager.get_collection("map_scans")
    if coll_scans is not None:
        total_scans = coll_scans.count_documents({})
    else:
        total_scans = len(db_manager.json_db.find("map_scans"))

    # 3. Total Leads
    coll_leads = db_manager.get_collection("leads")
    if coll_leads is not None:
        total_leads = coll_leads.count_documents({})
    else:
        total_leads = len(db_manager.json_db.find("leads"))

    # 4. Total Credits Consumed (sum of credit_transactions creditsUsed)
    coll_tx = db_manager.get_collection("credit_transactions")
    total_credits_used = 0
    if coll_tx is not None:
        cursor = coll_tx.aggregate([
            {"$group": {"_id": None, "total": {"$sum": "$creditsUsed"}}}
        ])
        results = list(cursor)
        if results:
            total_credits_used = results[0]["total"]
    else:
        txs = db_manager.json_db.find("credit_transactions")
        total_credits_used = sum(tx.get("creditsUsed", 0) for tx in txs)

    # 5. Recent Signups (Top 5 sorted by createdAt desc)
    def get_user_created_at(usr):
        return usr.get("createdAt") or ""
    
    sorted_users = sorted(users, key=get_user_created_at, reverse=True)
    recent_signups = []
    for u in sorted_users[:5]:
        recent_signups.append({
            "id": u.get("id"),
            "fullName": u.get("fullName"),
            "email": u.get("email"),
            "role": u.get("role", "user"),
            "createdAt": u.get("createdAt") or ""
        })

    # 6. Recent Subscriptions (Top 5 sorted by updatedAt desc)
    def get_sub_updated_at(s):
        return s.get("updatedAt") or s.get("resetDate") or ""
    
    sorted_subs = sorted(subs, key=get_sub_updated_at, reverse=True)
    recent_subscriptions = []
    for s in sorted_subs[:5]:
        u_id = s.get("userId")
        user_obj = users_map.get(u_id, {})
        recent_subscriptions.append({
            "userId": u_id,
            "fullName": user_obj.get("fullName", "Unknown User"),
            "email": user_obj.get("email", "unknown@mapflow.ai"),
            "plan": s.get("plan", "FREE"),
            "creditLimit": s.get("creditLimit", 25),
            "updatedAt": s.get("updatedAt") or s.get("resetDate") or ""
        })

    return {
        "success": True,
        "data": {
            "totalUsers": total_users,
            "freeTiers": free_count,
            "starterTiers": starter_count,
            "agencyTiers": agency_count,
            "totalScans": total_scans,
            "totalLeads": total_leads,
            "totalCreditsUsed": total_credits_used,
            "dbMode": "JSON_FALLBACK" if db_manager.use_json_fallback else "MONGODB",
            "recentSignups": recent_signups,
            "recentSubscriptions": recent_subscriptions
        }
    }

@router.get("/users")
def get_users_list(admin_user: dict = Depends(get_current_admin_user)):
    # Get all users
    coll_users = db_manager.get_collection("users")
    if coll_users is not None:
        users = list(coll_users.find({}))
    else:
        users = db_manager.json_db.find("users")

    # Get all subscriptions to attach credit balance info
    coll_subs = db_manager.get_collection("subscriptions")
    if coll_subs is not None:
        subs = list(coll_subs.find({}))
    else:
        subs = db_manager.json_db.find("subscriptions")

    # Map subs by userId
    subs_map = {sub["userId"]: sub for sub in subs if "userId" in sub}

    formatted_users = []
    for user in users:
        u_id = user.get("id")
        user_sub = subs_map.get(u_id, {})
        
        # Format user object
        user_data = {
            "id": u_id,
            "fullName": user.get("fullName"),
            "email": user.get("email"),
            "isVerified": user.get("isVerified", False),
            "role": user.get("role", "user"),
            "onboardingCompleted": user.get("onboardingCompleted", False),
            "companyName": user.get("companyName") or "N/A",
            "companyWebsite": user.get("companyWebsite") or "N/A",
            "plan": user_sub.get("plan", "FREE"),
            "creditLimit": user_sub.get("creditLimit", 25),
            "creditsUsed": user_sub.get("creditsUsed", 0),
            "resetDate": user_sub.get("resetDate") or "N/A",
        }
        formatted_users.append(user_data)

    return {"success": True, "data": formatted_users}

@router.put("/users/{user_id}/role")
def update_user_role(user_id: str, req: UpdateRoleRequest, admin_user: dict = Depends(get_current_admin_user)):
    if req.role not in ["user", "admin"]:
        raise HTTPException(status_code=400, detail="Invalid role. Must be 'user' or 'admin'.")

    # Find and update role
    coll = db_manager.get_collection("users")
    if coll is not None:
        result = coll.update_one({"id": user_id}, {"$set": {"role": req.role}})
        success = result.matched_count > 0
    else:
        success = db_manager.json_db.update_one("users", {"id": user_id}, {"$set": {"role": req.role}})

    if not success:
        raise HTTPException(status_code=404, detail="User not found")

    return {"success": True, "message": f"User role updated to '{req.role}'"}

@router.put("/users/{user_id}/credits")
def adjust_user_credits(user_id: str, req: AdjustCreditsRequest, admin_user: dict = Depends(get_current_admin_user)):
    coll_subs = db_manager.get_collection("subscriptions")
    
    update_data = {
        "creditLimit": req.creditLimit,
        "creditsUsed": req.creditsUsed
    }

    # Ensure subscription document exists for user
    if coll_subs is not None:
        sub = coll_subs.find_one({"userId": user_id})
        if not sub:
            # Create a default FREE sub first
            coll_subs.insert_one({
                "userId": user_id,
                "plan": "FREE",
                "creditLimit": req.creditLimit,
                "creditsUsed": req.creditsUsed,
                "resetDate": ""
            })
            success = True
        else:
            result = coll_subs.update_one({"userId": user_id}, {"$set": update_data})
            success = result.matched_count > 0
    else:
        sub = db_manager.json_db.find_one("subscriptions", {"userId": user_id})
        if not sub:
            db_manager.json_db.insert_one("subscriptions", {
                "userId": user_id,
                "plan": "FREE",
                "creditLimit": req.creditLimit,
                "creditsUsed": req.creditsUsed,
                "resetDate": ""
            })
            success = True
        else:
            success = db_manager.json_db.update_one("subscriptions", {"userId": user_id}, {"$set": update_data})

    if not success:
        raise HTTPException(status_code=404, detail="Subscription record not found")

    return {"success": True, "message": "User credits adjusted successfully"}

@router.delete("/users/{user_id}")
def delete_user(user_id: str, admin_user: dict = Depends(get_current_admin_user)):
    # Prevent admin from self-deletion
    if user_id == admin_user.get("id"):
        raise HTTPException(status_code=400, detail="Admins cannot delete their own account.")

    # List of collections to cascade delete for the user
    collections_by_userid = ["users", "subscriptions", "credit_transactions", "businesses", "leads", "map_scans", "scan_schedules", "outreach_activities", "ai_usage", "integrations", "webhooks"]

    coll_users = db_manager.get_collection("users")
    user_deleted = False

    if coll_users is not None:
        # Delete from MongoDB
        result = coll_users.delete_one({"id": user_id})
        user_deleted = result.deleted_count > 0
        if user_deleted:
            # Cascade delete in other collections
            for c_name in collections_by_userid:
                if c_name != "users":
                    coll = db_manager.get_collection(c_name)
                    if coll is not None:
                        coll.delete_many({"userId": user_id})
    else:
        # Delete from fallback JSON
        user_deleted = db_manager.json_db.delete_one("users", {"id": user_id})
        if user_deleted:
            # Cascade delete in other collections
            for c_name in collections_by_userid:
                if c_name != "users":
                    # Delete all matches
                    while db_manager.json_db.delete_one(c_name, {"userId": user_id}):
                        pass

    if not user_deleted:
        raise HTTPException(status_code=404, detail="User not found")

    return {"success": True, "message": f"User {user_id} and all their records deleted successfully"}

@router.get("/scans")
def get_all_scans(admin_user: dict = Depends(get_current_admin_user)):
    coll_s = db_manager.get_collection("map_scans")
    if coll_s is not None:
        # Retrieve all scans
        scans = list(coll_s.find({}))
    else:
        scans = db_manager.json_db.find("map_scans")

    # Map user info to scans
    coll_users = db_manager.get_collection("users")
    if coll_users is not None:
        users = list(coll_users.find({}))
    else:
        users = db_manager.json_db.find("users")

    users_map = {u["id"]: u["email"] for u in users if "id" in u}

    formatted_scans = []
    for scan in scans:
        s_id = scan.get("id")
        u_id = scan.get("userId")
        
        # Handle stringify MongoDB id
        if "_id" in scan:
            scan["_id"] = str(scan["_id"])
            
        scan_data = {
            **scan,
            "userEmail": users_map.get(u_id, "unknown@mapflow.ai")
        }
        formatted_scans.append(scan_data)

    return {"success": True, "data": formatted_scans}
