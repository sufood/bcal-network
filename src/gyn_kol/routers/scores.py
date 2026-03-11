from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from gyn_kol.database import get_session
from gyn_kol.scoring.early_adopter import score_all_early_adopter
from gyn_kol.scoring.influence import score_all_clinicians
from gyn_kol.scoring.tiers import assign_all_tiers

router = APIRouter(prefix="/scores", tags=["scoring"])


@router.post("/recalculate")
async def recalculate_scores(session: AsyncSession = Depends(get_session)) -> dict:
    influence_count = await score_all_clinicians(session)
    ea_count = await score_all_early_adopter(session)
    tier_count = await assign_all_tiers(session)
    return {
        "influence_scored": influence_count,
        "early_adopter_scored": ea_count,
        "tiers_assigned": tier_count,
    }
