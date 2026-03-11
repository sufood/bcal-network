import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gyn_kol.models.clinician import MasterClinician

logger = logging.getLogger(__name__)

# Keywords that signal technology-related publications
TECH_PUB_KEYWORDS = [
    "robotic",
    "robot-assisted",
    "minimally invasive",
    "laparoscopic",
    "da vinci",
    "single-port",
    "simulation",
    "virtual reality",
    "3d",
    "artificial intelligence",
]


def calculate_early_adopter_score(clinician: MasterClinician) -> float:
    """Flag-based early adopter score: 0–10."""
    score = 0.0
    flags = clinician.source_flags or []
    specialty = (clinician.specialty or "").lower()

    # MIS or oncology specialty: +2
    if any(kw in specialty for kw in ["minimally invasive", "mis", "oncology", "gynaecologic oncology"]):
        score += 2

    # Multiple source flags suggest broad engagement: +2 proxy for private/mixed practice
    if len(flags) >= 3:
        score += 2

    # Multiple hospital affiliations: +1
    # (approximated by having both hospital and college source flags)
    if "hospital" in flags and any(f in flags for f in ["ranzcog", "ages"]):
        score += 1

    # Technology-related publications: +2
    # This will be enhanced once we have full-text access
    if clinician.pub_count and clinician.pub_count >= 5:
        score += 2

    # Training / simulation role: +1
    if "university" in flags:
        score += 1

    # Prior new device adoption signal: +2
    # Approximated by review keyword mentions
    if clinician.review_count and clinician.review_count > 10:
        score += 2

    return min(score, 10.0)


async def score_all_early_adopter(session: AsyncSession) -> int:
    result = await session.execute(select(MasterClinician))
    clinicians = result.scalars().all()

    scored = 0
    for c in clinicians:
        c.early_adopter_score = calculate_early_adopter_score(c)
        scored += 1

    await session.commit()
    logger.info("Scored %d clinicians for early adopter", scored)
    return scored
