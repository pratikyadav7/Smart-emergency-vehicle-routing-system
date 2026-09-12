from fastapi import APIRouter
from backend.app.services.history_service import get_history

router = APIRouter()


@router.get("/history")
def history():
    return get_history()