import uuid
import random
from fastapi import APIRouter, HTTPException, status
from app.schemas.schemas import UserSignUp, UserLogin, OTPVerify
from app.core.security import get_password_hash, verify_password, create_access_token
from app.core.database import db_manager
from app.services.credit_service import CreditService

router = APIRouter()

@router.post("/signup")
async def signup(user_data: UserSignUp):
    coll = db_manager.get_collection("users")
    if coll is not None:
        existing = coll.find_one({"email": user_data.email})
    else:
        existing = db_manager.json_db.find_one("users", {"email": user_data.email})

    if existing:
        raise HTTPException(status_code=400, detail="User with this email already exists")

    otp_code = str(random.randint(100000, 999999))
    user_id = str(uuid.uuid4())
    new_user = {
        "id": user_id,
        "fullName": user_data.fullName,
        "email": user_data.email,
        "passwordHash": get_password_hash(user_data.password),
        "isVerified": False,
        "otpCode": otp_code,
        "onboardingCompleted": False
    }

    if coll is not None:
        coll.insert_one(new_user)
    else:
        db_manager.json_db.insert_one("users", new_user)

    # Initialize credit balance
    CreditService.get_user_credits(user_id)

    return {
        "success": True,
        "message": "User registered successfully. Verification OTP generated.",
        "otpCode": otp_code,  # Sent for dev convenience
        "userId": user_id
    }

@router.post("/verify-otp")
async def verify_otp(otp_data: OTPVerify):
    coll = db_manager.get_collection("users")
    if coll is not None:
        user = coll.find_one({"email": otp_data.email})
    else:
        user = db_manager.json_db.find_one("users", {"email": otp_data.email})

    if not user or user.get("otpCode") != otp_data.otpCode:
        raise HTTPException(status_code=400, detail="Invalid or expired OTP code")

    # Mark verified
    if coll is not None:
        coll.update_one({"email": otp_data.email}, {"$set": {"isVerified": True, "otpCode": None}})
    else:
        db_manager.json_db.update_one("users", {"email": otp_data.email}, {"$set": {"isVerified": True, "otpCode": None}})

    token = create_access_token({"sub": user["id"], "email": user["email"]})
    return {
        "success": True,
        "token": token,
        "user": {
            "id": user["id"],
            "fullName": user["fullName"],
            "email": user["email"],
            "onboardingCompleted": user.get("onboardingCompleted", False)
        }
    }

@router.post("/login")
async def login(login_data: UserLogin):
    coll = db_manager.get_collection("users")
    if coll is not None:
        user = coll.find_one({"email": login_data.email})
    else:
        user = db_manager.json_db.find_one("users", {"email": login_data.email})

    if not user or not verify_password(login_data.password, user.get("passwordHash", "")):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = create_access_token({"sub": user["id"], "email": user["email"]})
    return {
        "success": True,
        "token": token,
        "user": {
            "id": user["id"],
            "fullName": user["fullName"],
            "email": user["email"],
            "onboardingCompleted": user.get("onboardingCompleted", False)
        }
    }
