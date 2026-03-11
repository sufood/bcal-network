from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from gyn_kol.database import get_session
from gyn_kol.models.audit_log import AuditLog
from gyn_kol.models.clinician import MasterClinician
from gyn_kol.models.clinician_profile import ClinicianProfile
from gyn_kol.schemas.clinician import ClinicianDetail, ClinicianListItem, ClinicianListResponse, ScoreOverride

router = APIRouter(prefix="/clinicians", tags=["clinicians"])


@router.get("", response_model=ClinicianListResponse)
async def list_clinicians(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    tier: int | None = None,
    state: str | None = None,
    specialty: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> ClinicianListResponse:
    query = select(MasterClinician)

    if tier is not None:
        query = query.where(MasterClinician.tier == tier)
    if state:
        query = query.where(MasterClinician.state == state)
    if specialty:
        query = query.where(MasterClinician.specialty.ilike(f"%{specialty}%"))

    # Total count
    count_query = select(func.count()).select_from(query.subquery())
    total = (await session.execute(count_query)).scalar() or 0

    # Paginate
    query = query.order_by(MasterClinician.influence_score.desc().nulls_last())
    query = query.offset((page - 1) * page_size).limit(page_size)

    result = await session.execute(query)
    clinicians = result.scalars().all()

    return ClinicianListResponse(
        items=[ClinicianListItem.model_validate(c) for c in clinicians],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{clinician_id}", response_model=ClinicianDetail)
async def get_clinician(
    clinician_id: str,
    session: AsyncSession = Depends(get_session),
) -> ClinicianDetail:
    result = await session.execute(
        select(MasterClinician).where(MasterClinician.clinician_id == clinician_id)
    )
    clinician = result.scalar_one_or_none()
    if not clinician:
        raise HTTPException(status_code=404, detail="Clinician not found")

    # Get profile if exists
    profile_result = await session.execute(
        select(ClinicianProfile).where(ClinicianProfile.clinician_id == clinician_id)
    )
    profile = profile_result.scalar_one_or_none()

    detail = ClinicianDetail.model_validate(clinician)
    if profile:
        detail.profile_summary = profile.profile_summary
        detail.engagement_approach = profile.engagement_approach

    return detail


@router.patch("/{clinician_id}/score")
async def override_score(
    clinician_id: str,
    override: ScoreOverride,
    session: AsyncSession = Depends(get_session),
) -> dict:
    result = await session.execute(
        select(MasterClinician).where(MasterClinician.clinician_id == clinician_id)
    )
    clinician = result.scalar_one_or_none()
    if not clinician:
        raise HTTPException(status_code=404, detail="Clinician not found")

    changes = []

    if override.influence_score is not None and override.influence_score != clinician.influence_score:
        changes.append(AuditLog(
            clinician_id=clinician_id,
            field_changed="influence_score",
            old_value=str(clinician.influence_score),
            new_value=str(override.influence_score),
            changed_by=override.changed_by,
        ))
        clinician.influence_score = override.influence_score

    if override.early_adopter_score is not None and override.early_adopter_score != clinician.early_adopter_score:
        changes.append(AuditLog(
            clinician_id=clinician_id,
            field_changed="early_adopter_score",
            old_value=str(clinician.early_adopter_score),
            new_value=str(override.early_adopter_score),
            changed_by=override.changed_by,
        ))
        clinician.early_adopter_score = override.early_adopter_score

    if override.tier is not None and override.tier != clinician.tier:
        changes.append(AuditLog(
            clinician_id=clinician_id,
            field_changed="tier",
            old_value=str(clinician.tier),
            new_value=str(override.tier),
            changed_by=override.changed_by,
        ))
        clinician.tier = override.tier

    for log in changes:
        session.add(log)

    await session.commit()
    return {"updated_fields": len(changes)}
