from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from gyn_kol.database import get_session
from gyn_kol.exports.excel import generate_ranked_list_excel

router = APIRouter(prefix="/exports", tags=["exports"])


@router.get("/ranked-list")
async def export_ranked_list(session: AsyncSession = Depends(get_session)) -> StreamingResponse:
    output = await generate_ranked_list_excel(session)
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=kol_ranked_list.xlsx"},
    )


@router.get("/crm")
async def export_crm(session: AsyncSession = Depends(get_session)) -> StreamingResponse:
    from gyn_kol.exports.crm import generate_crm_csv

    output = await generate_crm_csv(session)
    return StreamingResponse(
        output,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=kol_crm_export.csv"},
    )
