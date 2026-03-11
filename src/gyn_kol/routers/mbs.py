from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from gyn_kol.database import get_session
from gyn_kol.models.clinician_mbs import ClinicianMbs
from gyn_kol.models.mbs_item import MbsItem
from gyn_kol.schemas.mbs import (
    ClinicianMbsListResponse,
    ClinicianMbsResponse,
    MbsItemListResponse,
    MbsItemResponse,
    MbsLinkageSummary,
)

router = APIRouter(prefix="/mbs", tags=["mbs"])


@router.post("/ingest")
async def ingest_mbs_items(
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Trigger MBS XML download and parse target items."""
    from gyn_kol.ingestion.mbs import fetch_mbs_items

    count = await fetch_mbs_items(session)
    return {"items_stored": count}


@router.post("/link", response_model=MbsLinkageSummary)
async def run_mbs_linkage(
    session: AsyncSession = Depends(get_session),
) -> MbsLinkageSummary:
    """Link MBS items to clinicians based on AHPRA specialty rules."""
    from gyn_kol.ingestion.mbs_linkage import link_mbs_to_clinicians

    result = await link_mbs_to_clinicians(session)
    return MbsLinkageSummary(**result)


@router.get("/items", response_model=MbsItemListResponse)
async def list_mbs_items(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
) -> MbsItemListResponse:
    """List stored MBS items of interest."""
    query = select(MbsItem)

    count_query = select(func.count()).select_from(query.subquery())
    total = (await session.execute(count_query)).scalar() or 0

    query = query.order_by(MbsItem.item_number)
    query = query.offset((page - 1) * page_size).limit(page_size)

    result = await session.execute(query)
    items = result.scalars().all()

    return MbsItemListResponse(
        items=[MbsItemResponse.model_validate(i) for i in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/items/{item_number}", response_model=MbsItemResponse)
async def get_mbs_item(
    item_number: str,
    session: AsyncSession = Depends(get_session),
) -> MbsItemResponse:
    """Get a single MBS item by item number."""
    result = await session.execute(
        select(MbsItem).where(MbsItem.item_number == item_number)
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail=f"MBS item {item_number} not found")
    return MbsItemResponse.model_validate(item)


@router.get("/mappings", response_model=ClinicianMbsListResponse)
async def list_mbs_mappings(
    clinician_id: str | None = None,
    item_number: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
) -> ClinicianMbsListResponse:
    """List clinician–MBS item mappings with optional filters."""
    query = select(ClinicianMbs)

    if clinician_id:
        query = query.where(ClinicianMbs.clinician_id == clinician_id)
    if item_number:
        # Join to MbsItem to filter by item_number
        query = query.join(MbsItem, ClinicianMbs.mbs_item_id == MbsItem.mbs_item_id)
        query = query.where(MbsItem.item_number == item_number)

    count_query = select(func.count()).select_from(query.subquery())
    total = (await session.execute(count_query)).scalar() or 0

    query = query.order_by(ClinicianMbs.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)

    result = await session.execute(query)
    mappings = result.scalars().all()

    return ClinicianMbsListResponse(
        items=[ClinicianMbsResponse.model_validate(m) for m in mappings],
        total=total,
        page=page,
        page_size=page_size,
    )
