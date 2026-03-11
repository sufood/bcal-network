from pydantic import BaseModel


class CanreferProfileResponse(BaseModel):
    model_config = {"from_attributes": True}

    profile_id: str
    name_raw: str
    given_name: str | None = None
    family_name: str | None = None
    honorific_prefix: str | None = None
    gender: str | None = None
    state: str | None = None
    slug: str | None = None
    job_titles: list[str] | None = None
    languages: list[str] | None = None
    work_locations: list[dict] | None = None  # type: ignore[type-arg]
    hospitals: list[dict] | None = None  # type: ignore[type-arg]
    mdts: list[dict] | None = None  # type: ignore[type-arg]
    phone: str | None = None
    profile_url: str | None = None


class CanreferListResponse(BaseModel):
    items: list[CanreferProfileResponse]
    total: int
    page: int
    page_size: int


class AhpraRegistrationResponse(BaseModel):
    model_config = {"from_attributes": True}

    registration_id: str
    name_raw: str
    registration_number: str | None = None
    profession: str | None = None
    registration_type: str | None = None
    registration_status: str | None = None
    state: str | None = None
    search_profession: str | None = None


class AhpraListResponse(BaseModel):
    items: list[AhpraRegistrationResponse]
    total: int
    page: int
    page_size: int


class VerificationResponse(BaseModel):
    model_config = {"from_attributes": True}

    verification_id: str
    canrefer_profile_id: str | None = None
    ahpra_registration_id: str | None = None
    match_score: float | None = None
    match_method: str | None = None
    verification_status: str | None = None
    notes: str | None = None
    verified_by: str | None = None


class VerificationListResponse(BaseModel):
    items: list[VerificationResponse]
    total: int
    page: int
    page_size: int


class VerificationSummary(BaseModel):
    verified: int
    unmatched_canrefer: int
    unmatched_ahpra: int
    total_canrefer: int
    total_ahpra: int
