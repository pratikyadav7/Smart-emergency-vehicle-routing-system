from fastapi import APIRouter
from backend.app.services.chaos_service import chaos_status

router = APIRouter()


@router.get("/chaos")
def get_chaos():
    return chaos_status()