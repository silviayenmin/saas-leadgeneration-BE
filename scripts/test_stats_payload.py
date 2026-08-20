import sys
import os
import json

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.core.database import db_manager
from app.api.admin import get_system_stats

def main():
    db_manager.connect()
    try:
        # Mock admin_user dict parameter since it is Depends(get_current_admin_user)
        stats_response = get_system_stats(admin_user={"email": "admin@mapflow.ai", "role": "admin"})
        print("STATS RESPONSE JSON payload:")
        print(json.dumps(stats_response, indent=2))
    except Exception as e:
        print("ERROR invoking get_system_stats:", e)

if __name__ == "__main__":
    main()
