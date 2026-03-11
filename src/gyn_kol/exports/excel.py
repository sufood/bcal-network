import io
import logging

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gyn_kol.models.clinician import MasterClinician
from gyn_kol.models.clinician_profile import ClinicianProfile

logger = logging.getLogger(__name__)


async def generate_ranked_list_excel(session: AsyncSession) -> io.BytesIO:
    result = await session.execute(
        select(MasterClinician).order_by(MasterClinician.influence_score.desc().nulls_last())
    )
    clinicians = result.scalars().all()

    # Get profiles
    profile_result = await session.execute(select(ClinicianProfile))
    profiles = {p.clinician_id: p for p in profile_result.scalars().all()}

    rows = []
    for i, c in enumerate(clinicians, 1):
        profile = profiles.get(c.clinician_id)
        rows.append({
            "Rank": i,
            "Name": c.name_display,
            "Tier": c.tier,
            "Influence Score": c.influence_score,
            "Early Adopter Score": c.early_adopter_score,
            "State": c.state,
            "Specialty": c.specialty,
            "Institution": c.primary_institution,
            "Publications": c.pub_count,
            "Trials": c.trial_count,
            "Grants": c.grant_count,
            "Sources": ", ".join(c.source_flags or []),
            "Profile Summary": profile.profile_summary if profile else "",
            "Engagement Approach": profile.engagement_approach if profile else "",
        })

    df = pd.DataFrame(rows)
    output = io.BytesIO()
    df.to_excel(output, index=False, sheet_name="KOL Ranked List", engine="openpyxl")
    output.seek(0)
    return output
