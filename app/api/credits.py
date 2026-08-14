from fastapi import APIRouter, Depends
from app.core.security import get_current_user_id
from app.services.credit_service import CreditService
from app.core.database import db_manager

router = APIRouter()

@router.get("/balance")
async def get_credit_balance(user_id: str = Depends(get_current_user_id)):
    credits = CreditService.get_user_credits(user_id)
    return {"success": True, "data": credits}

@router.get("/transactions")
async def get_credit_transactions(user_id: str = Depends(get_current_user_id)):
    coll_tx = db_manager.get_collection("credit_transactions")
    if coll_tx is not None:
        transactions = list(coll_tx.find({"userId": user_id}))
    else:
        transactions = db_manager.json_db.find("credit_transactions", {"userId": user_id})

    return {"success": True, "data": transactions}
