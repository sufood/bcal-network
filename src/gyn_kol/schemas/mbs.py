from pydantic import BaseModel


class MbsItemResponse(BaseModel):
    model_config = {"from_attributes": True}

    mbs_item_id: str
    item_number: str
    description: str | None = None
    category: str | None = None
    group: str | None = None
    subgroup: str | None = None
    schedule_fee: float | None = None
    benefit_75: float | None = None
    benefit_85: float | None = None
    gynaecology_relevance: str | None = None
    item_start_date: str | None = None
    item_end_date: str | None = None


class MbsItemListResponse(BaseModel):
    items: list[MbsItemResponse]
    total: int
    page: int
    page_size: int


class ClinicianMbsResponse(BaseModel):
    model_config = {"from_attributes": True}

    mapping_id: str
    clinician_id: str
    mbs_item_id: str
    relevance_basis: str | None = None
    link_method: str | None = None


class ClinicianMbsListResponse(BaseModel):
    items: list[ClinicianMbsResponse]
    total: int
    page: int
    page_size: int


class MbsLinkageSummary(BaseModel):
    total_mappings: int
    procedure_links: int
    consultation_links: int
    clinicians_linked: int
