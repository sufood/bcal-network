from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from gyn_kol.database import get_session
from gyn_kol.graph.builder import build_coauthorship_graph
from gyn_kol.graph.export import export_json

router = APIRouter(prefix="/graph", tags=["graph"])


@router.get("")
async def get_graph(session: AsyncSession = Depends(get_session)) -> dict:
    G = await build_coauthorship_graph(session)
    return export_json(G)
