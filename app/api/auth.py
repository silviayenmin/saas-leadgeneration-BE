import uuid
import random
from fastapi import APIRouter, HTTPException, status, Depends
from app.schemas.schemas import UserSignUp, UserLogin, OTPVerify, ResendOTPRequest, ForgotPasswordRequest, ResetPasswordRequest
from app.core.security import get_password_hash, verify_password, create_access_token, get_current_user_id
from app.core.database import db_manager
from app.services.credit_service import CreditService
from app.services.email_service import EmailService

router = APIRouter()

# Note: Using standard 'def' (not async def) because pymongo is a synchronous database driver.
# FastAPI automatically runs standard 'def' route handlers in a thread pool, preventing any asyncio loop blocking.

@router.post("/signup")
def signup(user_data: UserSignUp):
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

    # Initialize default free plan & credit balance
    CreditService.get_user_credits(user_id)

    # Fire background thread for email delivery
    EmailService.send_async_otp_email(user_data.email, otp_code)

    return {
        "success": True,
        "message": f"Verification code sent to {user_data.email}",
        "userId": user_id
    }

@router.post("/verify-otp")
def verify_otp(otp_data: OTPVerify):
    coll = db_manager.get_collection("users")
    if coll is not None:
        user = coll.find_one({"email": otp_data.email})
    else:
        user = db_manager.json_db.find_one("users", {"email": otp_data.email})

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user.get("otpCode") != otp_data.otpCode:
        raise HTTPException(status_code=400, detail="Invalid or expired verification code")

    # Mark verified
    update_data = {"isVerified": True, "otpCode": None}
    if coll is not None:
        coll.update_one({"email": otp_data.email}, {"$set": update_data})
    else:
        db_manager.json_db.update_one("users", {"email": otp_data.email}, {"$set": update_data})

    user.update(update_data)
    token = create_access_token({"sub": user["id"], "email": user["email"]})

    return {
        "success": True,
        "message": "Email verified successfully!",
        "token": token,
        "user": {
            "id": user["id"],
            "fullName": user["fullName"],
            "email": user["email"],
            "isVerified": True,
            "onboardingCompleted": user.get("onboardingCompleted", False)
        }
    }

@router.post("/resend-otp")
def resend_otp(req: ResendOTPRequest):
    coll = db_manager.get_collection("users")
    if coll is not None:
        user = coll.find_one({"email": req.email})
    else:
        user = db_manager.json_db.find_one("users", {"email": req.email})

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    new_otp = str(random.randint(100000, 999999))
    if coll is not None:
        coll.update_one({"email": req.email}, {"$set": {"otpCode": new_otp}})
    else:
        db_manager.json_db.update_one("users", {"email": req.email}, {"$set": {"otpCode": new_otp}})

    # Fire background thread for email delivery
    EmailService.send_async_otp_email(req.email, new_otp)

    return {
        "success": True,
        "message": f"A new verification code has been sent to {req.email}"
    }

@router.post("/login")
def login(login_data: UserLogin):
    coll = db_manager.get_collection("users")
    if coll is not None:
        user = coll.find_one({"email": login_data.email})
    else:
        user = db_manager.json_db.find_one("users", {"email": login_data.email})

    if not user or not verify_password(login_data.password, user.get("passwordHash", "")):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not user.get("isVerified", False):
        # Generate fresh OTP if not verified yet
        new_otp = str(random.randint(100000, 999999))
        if coll is not None:
            coll.update_one({"email": login_data.email}, {"$set": {"otpCode": new_otp}})
        else:
            db_manager.json_db.update_one("users", {"email": login_data.email}, {"$set": {"otpCode": new_otp}})
            
        EmailService.send_async_otp_email(login_data.email, new_otp)

        return {
            "success": False,
            "requiresOtp": True,
            "message": "Email not verified. A verification code has been sent to your email.",
            "email": user["email"]
        }

    token = create_access_token({"sub": user["id"], "email": user["email"]})
    return {
        "success": True,
        "token": token,
        "user": {
            "id": user["id"],
            "fullName": user["fullName"],
            "email": user["email"],
            "isVerified": True,
            "onboardingCompleted": user.get("onboardingCompleted", False)
        }
    }

@router.post("/forgot-password")
def forgot_password(req: ForgotPasswordRequest):
    coll = db_manager.get_collection("users")
    if coll is not None:
        user = coll.find_one({"email": req.email})
    else:
        user = db_manager.json_db.find_one("users", {"email": req.email})

    if not user:
        raise HTTPException(status_code=404, detail="No account registered with this email")

    reset_code = str(random.randint(100000, 999999))
    if coll is not None:
        coll.update_one({"email": req.email}, {"$set": {"resetCode": reset_code}})
    else:
        db_manager.json_db.update_one("users", {"email": req.email}, {"$set": {"resetCode": reset_code}})

    EmailService.send_async_reset_password_email(req.email, reset_code)

    return {
        "success": True,
        "message": f"Password reset verification code sent to {req.email}",
        "resetCode": reset_code
    }

@router.post("/reset-password")
def reset_password(req: ResetPasswordRequest):
    coll = db_manager.get_collection("users")
    if coll is not None:
        user = coll.find_one({"email": req.email})
    else:
        user = db_manager.json_db.find_one("users", {"email": req.email})

    if not user:
        raise HTTPException(status_code=404, detail="No account registered with this email")

    if not user.get("resetCode") or user.get("resetCode") != req.resetCode:
        raise HTTPException(status_code=400, detail="Invalid or expired verification code")

    new_hash = get_password_hash(req.newPassword)
    update_data = {"passwordHash": new_hash, "resetCode": None}

    if coll is not None:
        coll.update_one({"email": req.email}, {"$set": update_data})
    else:
        db_manager.json_db.update_one("users", {"email": req.email}, {"$set": update_data})

    return {
        "success": True,
        "message": "Password reset successfully. You can now sign in with your new password."
    }

from pydantic import BaseModel

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

@router.post("/change-password")
def change_password(req: ChangePasswordRequest, user_id: str = Depends(get_current_user_id)):
    coll = db_manager.get_collection("users")
    if coll is not None:
        user = coll.find_one({"id": user_id})
    else:
        user = db_manager.json_db.find_one("users", {"id": user_id})

    if not user:
        raise HTTPException(status_code=404, detail="User account not found")

    # Verify current password
    if not verify_password(req.current_password, user.get("passwordHash", "")):
        raise HTTPException(status_code=400, detail="Incorrect current password")

    new_hash = get_password_hash(req.new_password)
    
    if coll is not None:
        coll.update_one({"id": user_id}, {"$set": {"passwordHash": new_hash}})
    else:
        db_manager.json_db.update_one("users", {"id": user_id}, {"$set": {"passwordHash": new_hash}})

    return {
        "success": True,
        "message": "Password updated successfully!"
    }

