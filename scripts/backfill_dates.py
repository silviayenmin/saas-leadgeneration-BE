import sys
import os
import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.core.database import db_manager

def main():
    db_manager.connect()
    
    # 1. Backfill User createdAt dates
    coll_users = db_manager.get_collection("users")
    if coll_users is not None:
        users = list(coll_users.find({}))
        print(f"Found {len(users)} users. Backfilling 'createdAt'...")
        
        # Staggered dates for prominent test accounts to look extremely realistic
        custom_dates = {
            "silvia.yenmin@gmail.com": datetime.datetime(2026, 8, 20, 8, 30, 0),    # ~7 hours ago
            "test@mapflow.ai": datetime.datetime(2026, 8, 20, 11, 15, 0),           # ~5 hours ago
            "infantaa014@gmail.com": datetime.datetime(2026, 8, 20, 13, 45, 0),     # ~2 hours ago
            "admin@mapflow.ai": datetime.datetime(2026, 8, 18, 9, 20, 0),           # 2 days ago
            "john@example.com": datetime.datetime(2026, 8, 17, 14, 10, 0)           # 3 days ago
        }
        
        default_base = datetime.datetime(2026, 8, 15, 10, 0, 0)
        
        for idx, u in enumerate(users):
            email = u.get("email")
            if email in custom_dates:
                user_date = custom_dates[email]
            else:
                # stagger other users
                user_date = default_base - datetime.timedelta(days=idx % 5, hours=idx % 12)
                
            coll_users.update_one(
                {"_id": u["_id"]},
                {"$set": {"createdAt": user_date.isoformat() + "Z"}}
            )
            print(f"Updated user {email} -> {user_date.isoformat()}Z")
            
    # 2. Backfill Subscription updatedAt dates
    coll_subs = db_manager.get_collection("subscriptions")
    if coll_subs is not None:
        subs = list(coll_subs.find({}))
        print(f"\nFound {len(subs)} subscriptions. Backfilling 'updatedAt'...")
        
        for s in subs:
            reset_str = s.get("resetDate")
            if not reset_str:
                sub_date = datetime.datetime(2026, 8, 20, 10, 0, 0)
            else:
                try:
                    # Parse reset date (YYYY-MM-DD)
                    reset_date = datetime.datetime.strptime(reset_str, "%Y-%m-%d")
                    # If reset date is in 2027 (annual plan), subtract 1 year.
                    if reset_date.year == 2027:
                        sub_date = reset_date.replace(year=2026)
                    else:
                        # Otherwise subtract 1 month (30 days) for monthly renewal cycle
                        sub_date = reset_date - datetime.timedelta(days=30)
                except Exception:
                    sub_date = datetime.datetime(2026, 8, 20, 10, 0, 0)
            
            coll_subs.update_one(
                {"_id": s["_id"]},
                {"$set": {"updatedAt": sub_date.isoformat() + "Z"}}
            )
            print(f"Updated subscription for user {s.get('userId')} -> {sub_date.isoformat()}Z")
            
    print("\nBackfill complete!")

if __name__ == "__main__":
    main()
