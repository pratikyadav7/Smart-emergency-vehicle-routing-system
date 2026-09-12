from fastapi import APIRouter
from backend.app.services.hospital_service import hospitals

router = APIRouter()


@router.get("/hospitals")
def get_hospitals():
    return {
        "count": len(hospitals),
        "data": hospitals
    }