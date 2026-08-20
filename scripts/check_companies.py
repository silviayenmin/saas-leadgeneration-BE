import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.core.database import db_manager

def main():
    db_manager.connect()
    coll = db_manager.get_collection("users")
    if coll is not None:
        users = list(coll.find({}))
        for u in users:
            print("USER:", u.get("fullName"))
            print("  companyName:     ", repr(u.get("companyName")))
            print("  companyWebsite:  ", repr(u.get("companyWebsite")))
    else:
        print("MongoDB connection returned None")

if __name__ == "__main__":
    main()
