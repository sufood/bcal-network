import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import Mapped, mapped_column

from gyn_kol.database import Base


class CanreferProfile(Base):
    __tablename__ = "canrefer_profiles"

    profile_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name_raw: Mapped[str] = mapped_column(String(500))
    name_normalised: Mapped[str | None] = mapped_column(String(500), index=True)
    given_name: Mapped[str | None] = mapped_column(String(200))
    family_name: Mapped[str | None] = mapped_column(String(200))
    honorific_prefix: Mapped[str | None] = mapped_column(String(100))
    gender: Mapped[str | None] = mapped_column(String(20))
    state: Mapped[str | None] = mapped_column(String(50), index=True)
    slug: Mapped[str | None] = mapped_column(String(200), unique=True, index=True)
    job_titles: Mapped[list[Any] | None] = mapped_column(JSON)
    languages: Mapped[list[Any] | None] = mapped_column(JSON)
    work_locations: Mapped[list[Any] | None] = mapped_column(JSON)
    hospitals: Mapped[list[Any] | None] = mapped_column(JSON)
    mdts: Mapped[list[Any] | None] = mapped_column(JSON)
    phone: Mapped[str | None] = mapped_column(String(100))
    profile_url: Mapped[str | None] = mapped_column(String(500))
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=datetime.now)
