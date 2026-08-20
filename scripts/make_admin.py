import sys
import os
import argparse

# Add parent directory to sys.path to allow importing app
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import db_manager

def main():
    parser = argparse.ArgumentParser(description="Elevate a user to admin role.")
    parser.add_argument("--email", required=True, help="Email of the user to elevate.")
    args = parser.parse_args()

    email = args.email.strip().lower()

    # Connect database
    db_manager.connect()

    # Query MongoDB or fallback
    coll = db_manager.get_collection("users")
    if coll is not None:
        user = coll.find_one({"email": email})
    else:
        user = db_manager.json_db.find_one("users", {"email": email})

    if not user:
        print(f"Error: User with email '{email}' not found.")
        sys.exit(1)

    print(f"Found user: {user.get('fullName')} ({user.get('email')}), current role: '{user.get('role', 'user')}'")

    # Update role to admin
    if coll is not None:
        result = coll.update_one({"email": email}, {"$set": {"role": "admin"}})
        success = result.matched_count > 0
    else:
        success = db_manager.json_db.update_one("users", {"email": email}, {"$set": {"role": "admin"}})

    if success:
        print(f"Success: Elevated {email} to admin role!")
    else:
        print(f"Failed to elevate user.")

if __name__ == "__main__":
    main()
