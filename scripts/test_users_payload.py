import sys
import os
import json

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.core.database import db_manager
from app.api.admin import get_users_list

def main():
    db_manager.connect()
    try:
        users_response = get_users_list(admin_user={"email": "admin@mapflow.ai", "role": "admin"})
        print("USERS RESPONSE:")
        print(json.dumps(users_response, indent=2))
    except Exception as e:
        print("ERROR invoking get_users_list:", e)

if __name__ == "__main__":
    main()
