from datetime import datetime
import uuid
from typing import Dict, Any, Tuple
from app.core.config import settings
from app.core.database import db_manager

class CreditService:
    @staticmethod
    def get_user_credits(user_id: str) -> Dict[str, Any]:
        coll = db_manager.get_collection("subscriptions")
        if coll is not None:
            sub = coll.find_one({"userId": user_id})
        else:
            sub = db_manager.json_db.find_one("subscriptions", {"userId": user_id})

        if not sub:
            # Default free plan
            sub = {
                "userId": user_id,
                "plan": "FREE",
                "creditLimit": settings.FREE_CREDITS,
                "creditsUsed": 0,
                "resetDate": datetime.utcnow().strftime("%Y-%m-%d")
            }
            if coll is not None:
                coll.insert_one(sub)
            else:
                db_manager.json_db.insert_one("subscriptions", sub)

        credit_limit = sub.get("creditLimit", settings.FREE_CREDITS)
        credits_used = sub.get("creditsUsed", 0)
        credits_remaining = max(0, credit_limit - credits_used)
        
        return {
            "plan": sub.get("plan", "FREE"),
            "creditLimit": credit_limit,
            "creditsUsed": credits_used,
            "creditsRemaining": credits_remaining,
            "resetDate": sub.get("resetDate", "")
        }

    @staticmethod
    def check_and_deduct(user_id: str, action: str, cost: int) -> Tuple[bool, str, Dict[str, Any]]:
        credits_info = CreditService.get_user_credits(user_id)
        if credits_info["creditsRemaining"] < cost:
            return False, f"Insufficient credits. Requires {cost} credit(s). Please upgrade your plan.", credits_info

        # Record transaction
        balance_before = credits_info["creditsRemaining"]
        balance_after = balance_before - cost
        new_credits_used = credits_info["creditsUsed"] + cost

        coll_sub = db_manager.get_collection("subscriptions")
        if coll_sub is not None:
            coll_sub.update_one({"userId": user_id}, {"$set": {"creditsUsed": new_credits_used}})
        else:
            db_manager.json_db.update_one("subscriptions", {"userId": user_id}, {"$set": {"creditsUsed": new_credits_used}})

        transaction = {
            "id": str(uuid.uuid4()),
            "userId": user_id,
            "action": action,
            "creditsUsed": cost,
            "balanceBefore": balance_before,
            "balanceAfter": balance_after,
            "timestamp": datetime.utcnow().isoformat()
        }

        coll_tx = db_manager.get_collection("credit_transactions")
        if coll_tx is not None:
            coll_tx.insert_one(transaction)
        else:
            db_manager.json_db.insert_one("credit_transactions", transaction)

        updated_credits_info = CreditService.get_user_credits(user_id)
        return True, "Credits deducted successfully", updated_credits_info
