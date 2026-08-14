from fastapi import APIRouter, Depends, HTTPException
from app.core.security import get_current_user_id
from app.core.database import db_manager
from app.schemas.schemas import LeadPipelineUpdate

router = APIRouter()

@router.get("/board")
async def get_pipeline_board(user_id: str = Depends(get_current_user_id)):
    columns = [
        "Discovered",
        "Owner Identified",
        "Pitch Drafted",
        "Emailed",
        "Call Made",
        "Responded",
        "Closed Won"
    ]

    coll_l = db_manager.get_collection("leads")
    if coll_l is not None:
        leads = list(coll_l.find({"userId": user_id}))
    else:
        leads = db_manager.json_db.find("leads", {"userId": user_id})

    board = {col: [] for col in columns}
    for lead in leads:
        stage = lead.get("stage", "Discovered")
        if stage in board:
            board[stage].append(lead)
        else:
            board["Discovered"].append(lead)

    return {"success": True, "data": board}

@router.post("/update-stage")
async def update_lead_stage(payload: LeadPipelineUpdate, user_id: str = Depends(get_current_user_id)):
    coll_l = db_manager.get_collection("leads")
    update_data = {"stage": payload.stage}
    if payload.notes is not None:
        update_data["notes"] = payload.notes
    if payload.nextFollowUpAt is not None:
        update_data["nextFollowUpAt"] = payload.nextFollowUpAt

    if coll_l is not None:
        updated = coll_l.update_one({"id": payload.leadId, "userId": user_id}, {"$set": update_data})
    else:
        updated = db_manager.json_db.update_one("leads", {"id": payload.leadId, "userId": user_id}, {"$set": update_data})

    return {"success": True, "message": "Lead stage updated"}
