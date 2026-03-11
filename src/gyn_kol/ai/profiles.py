import asyncio
import logging
from datetime import datetime

from anthropic import AsyncAnthropic
from jinja2 import Template
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gyn_kol.models.clinician import MasterClinician
from gyn_kol.models.clinician_profile import ClinicianProfile

logger = logging.getLogger(__name__)

_semaphore = asyncio.Semaphore(5)

PROFILE_TEMPLATE = Template("""You are a medical affairs analyst. Generate a concise KOL profile summary and engagement approach for this clinician.

## Clinician Data
- **Name:** {{ name }}
- **Institution:** {{ institution or "Unknown" }}
- **State:** {{ state or "Unknown" }}
- **Specialty:** {{ specialty or "General O&G" }}
- **Publication Count:** {{ pub_count or 0 }}
- **Trial PI Roles:** {{ trial_count or 0 }}
- **Grant Awards:** {{ grant_count or 0 }}
- **Influence Score:** {{ influence_score or "N/A" }} / 100
- **Early Adopter Score:** {{ early_adopter_score or "N/A" }} / 10
- **Tier:** {{ tier or "Unassigned" }}
- **Data Sources:** {{ sources }}

## Instructions
1. Write a 2-3 sentence **Profile Summary** describing this clinician's research focus, clinical expertise, and standing in the Australian GYN community.
2. Write a 2-3 sentence **Engagement Approach** recommending how a medical device company should approach this KOL (e.g., advisory board, speaker program, clinical trial site, peer education).

Format your response as:
**Profile Summary:** [text]
**Engagement Approach:** [text]
""")


async def generate_profile(
    client: AsyncAnthropic, session: AsyncSession, clinician: MasterClinician
) -> ClinicianProfile | None:
    async with _semaphore:
        prompt = PROFILE_TEMPLATE.render(
            name=clinician.name_display,
            institution=clinician.primary_institution,
            state=clinician.state,
            specialty=clinician.specialty,
            pub_count=clinician.pub_count,
            trial_count=clinician.trial_count,
            grant_count=clinician.grant_count,
            influence_score=clinician.influence_score,
            early_adopter_score=clinician.early_adopter_score,
            tier=clinician.tier,
            sources=", ".join(clinician.source_flags or []),
        )

        try:
            response = await client.messages.create(
                model="claude-opus-4-6",
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}],
            )

            text = response.content[0].text

            # Parse response
            summary = ""
            approach = ""
            if "**Profile Summary:**" in text:
                parts = text.split("**Engagement Approach:**")
                summary = parts[0].replace("**Profile Summary:**", "").strip()
                if len(parts) > 1:
                    approach = parts[1].strip()

            profile = ClinicianProfile(
                clinician_id=clinician.clinician_id,
                profile_summary=summary or text,
                engagement_approach=approach,
                model_used="claude-opus-4-6",
                generated_at=datetime.utcnow(),
            )
            session.add(profile)
            return profile

        except Exception:
            logger.warning("Profile generation failed for %s", clinician.name_display, exc_info=True)
            return None


async def generate_profiles_batch(
    session: AsyncSession, api_key: str, tier_filter: list[int] | None = None
) -> int:
    if tier_filter is None:
        tier_filter = [1, 2]

    result = await session.execute(
        select(MasterClinician).where(MasterClinician.tier.in_(tier_filter))
    )
    clinicians = result.scalars().all()

    # Skip clinicians that already have profiles
    existing = await session.execute(select(ClinicianProfile.clinician_id))
    existing_ids = {row[0] for row in existing.all()}
    clinicians = [c for c in clinicians if c.clinician_id not in existing_ids]

    logger.info("Generating profiles for %d Tier %s clinicians", len(clinicians), tier_filter)

    client = AsyncAnthropic(api_key=api_key)
    generated = 0

    for clinician in clinicians:
        profile = await generate_profile(client, session, clinician)
        if profile:
            generated += 1

    await session.commit()
    logger.info("Generated %d profiles", generated)
    return generated
