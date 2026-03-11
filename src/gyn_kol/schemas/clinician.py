from datetime import datetime

from pydantic import BaseModel, Field


class ClinicianListItem(BaseModel):
    model_config = {"from_attributes": True}

    clinician_id: str
    name_display: str | None = None
    primary_institution: str | None = None
    state: str | None = None
    specialty: str | None = None
    influence_score: float | None = None
    early_adopter_score: float | None = None
    tier: int | None = None
    source_flags: list[str] | None = None


class ClinicianListResponse(BaseModel):
    items: list[ClinicianListItem]
    total: int
    page: int
    page_size: int


class ClinicianDetail(BaseModel):
    model_config = {"from_attributes": True}

    clinician_id: str
    name_display: str | None = None
    name_normalised: str | None = None
    primary_institution: str | None = None
    state: str | None = None
    specialty: str | None = None
    source_flags: list[str] | None = None
    pub_count: int | None = None
    trial_count: int | None = None
    grant_count: int | None = None
    review_count: int | None = None
    h_index_proxy: int | None = None
    influence_score: float | None = None
    early_adopter_score: float | None = None
    tier: int | None = None
    degree_centrality: float | None = None
    betweenness_centrality: float | None = None
    clustering_coefficient: float | None = None
    profile_summary: str | None = None
    engagement_approach: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ScoreOverride(BaseModel):
    influence_score: float | None = Field(None, ge=0, le=100)
    early_adopter_score: float | None = Field(None, ge=0, le=10)
    tier: int | None = Field(None, ge=1, le=4)
    changed_by: str = "manual"
