from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from gyn_kol.database import get_session
from gyn_kol.ingestion.canrefer import fetch_canrefer_profiles
from gyn_kol.ingestion.verification import verify_canrefer_against_ahpra
from gyn_kol.models.ahpra_registration import AhpraRegistration
from gyn_kol.models.canrefer_profile import CanreferProfile
from gyn_kol.models.registration_verification import RegistrationVerification
from gyn_kol.schemas.ingestion import (
    AhpraListResponse,
    AhpraRegistrationResponse,
    CanreferListResponse,
    CanreferProfileResponse,
    VerificationListResponse,
    VerificationResponse,
    VerificationSummary,
)

router = APIRouter(prefix="/ingestion", tags=["ingestion"])


@router.post("/canrefer")
async def ingest_canrefer(
    state: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Trigger Canrefer scraping. Optional state filter."""
    count = await fetch_canrefer_profiles(session, state=state)
    return {"profiles_stored": count}


@router.post("/ahpra")
async def ingest_ahpra(
    states: list[str] | None = Query(None),
    search_terms: list[str] | None = Query(None),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Trigger AHPRA scraping via Playwright. Optional state/profession filters."""
    from gyn_kol.ingestion.ahpra import fetch_ahpra_registrations

    count = await fetch_ahpra_registrations(session, search_terms=search_terms, states=states)
    return {"registrations_stored": count}


@router.post("/ahpra/scan-authors")
async def scan_authors_ahpra(
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Scan all Australian-affiliated PubMed authors against AHPRA (pre-resolution).

    Skips authors already matched in previous runs.
    """
    from gyn_kol.ingestion.ahpra_enrich import scan_authors_against_ahpra

    created = await scan_authors_against_ahpra(session)
    return {"registrations_created": created}


@router.post("/ahpra/enrich")
async def enrich_ahpra_specialty(
    limit: int = Query(500, ge=1, le=5000, description="Max clinicians to look up"),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Search AHPRA by name for clinicians missing specialty (post-resolution)."""
    from gyn_kol.ingestion.ahpra_enrich import enrich_specialty_from_ahpra

    updated = await enrich_specialty_from_ahpra(session, limit=limit)
    return {"clinicians_updated": updated}


@router.post("/verify", response_model=VerificationSummary)
async def run_verification(
    session: AsyncSession = Depends(get_session),
) -> VerificationSummary:
    """Cross-reference Canrefer specialists against AHPRA registrations."""
    result = await verify_canrefer_against_ahpra(session)
    return VerificationSummary(**result)


@router.get("/canrefer/profiles", response_model=CanreferListResponse)
async def list_canrefer_profiles(
    state: str | None = Query("NSW", description="Filter by state (default: NSW)"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
) -> CanreferListResponse:
    """List stored Canrefer gynaecological oncologist profiles."""
    query = select(CanreferProfile)
    if state:
        query = query.where(CanreferProfile.state == state.upper())

    count_query = select(func.count()).select_from(query.subquery())
    total = (await session.execute(count_query)).scalar() or 0

    query = query.order_by(CanreferProfile.family_name, CanreferProfile.given_name)
    query = query.offset((page - 1) * page_size).limit(page_size)

    result = await session.execute(query)
    profiles = result.scalars().all()

    return CanreferListResponse(
        items=[CanreferProfileResponse.model_validate(p) for p in profiles],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/ahpra/registrations", response_model=AhpraListResponse)
async def list_ahpra_registrations(
    state: str | None = Query("NSW", description="Filter by state (default: NSW)"),
    profession: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
) -> AhpraListResponse:
    """List stored AHPRA registrations."""
    query = select(AhpraRegistration)
    if state:
        query = query.where(AhpraRegistration.state == state.upper())
    if profession:
        query = query.where(AhpraRegistration.search_profession.ilike(f"%{profession}%"))

    count_query = select(func.count()).select_from(query.subquery())
    total = (await session.execute(count_query)).scalar() or 0

    query = query.order_by(AhpraRegistration.name_raw)
    query = query.offset((page - 1) * page_size).limit(page_size)

    result = await session.execute(query)
    registrations = result.scalars().all()

    return AhpraListResponse(
        items=[AhpraRegistrationResponse.model_validate(r) for r in registrations],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/verifications", response_model=VerificationListResponse)
async def list_verifications(
    status: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
) -> VerificationListResponse:
    """List verification results with optional status filter."""
    query = select(RegistrationVerification)
    if status:
        query = query.where(RegistrationVerification.verification_status == status)

    count_query = select(func.count()).select_from(query.subquery())
    total = (await session.execute(count_query)).scalar() or 0

    query = query.order_by(RegistrationVerification.verification_status, RegistrationVerification.match_score.desc().nulls_last())
    query = query.offset((page - 1) * page_size).limit(page_size)

    result = await session.execute(query)
    verifications = result.scalars().all()

    return VerificationListResponse(
        items=[VerificationResponse.model_validate(v) for v in verifications],
        total=total,
        page=page,
        page_size=page_size,
    )
