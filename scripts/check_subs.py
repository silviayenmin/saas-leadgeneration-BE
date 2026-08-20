import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.core.database import db_manager

def main():
    db_manager.connect()
    coll = db_manager.get_collection("subscriptions")
    if coll is not None:
        subs = list(coll.find({}))
        for s in subs:
            print("SUB:", s.get("userId"), "PLAN:", s.get("plan"), "UPDATED_AT:", s.get("updatedAt"), "RESET_DATE:", s.get("resetDate"), "KEYS:", list(s.keys()))
    else:
        print("MongoDB connection returned None")

if __name__ == "__main__":
    main()
