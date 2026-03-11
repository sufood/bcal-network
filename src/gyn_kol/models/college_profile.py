import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import Mapped, mapped_column

from gyn_kol.database import Base


class CollegeProfile(Base):
    __tablename__ = "college_profiles"

    profile_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name_raw: Mapped[str] = mapped_column(String(500))
    source: Mapped[str | None] = mapped_column(String(50))  # ranzcog, ages
    subspecialty: Mapped[str | None] = mapped_column(String(200))
    state: Mapped[str | None] = mapped_column(String(50))
    committee_roles: Mapped[list | None] = mapped_column(JSON)
    speaker_history: Mapped[list | None] = mapped_column(JSON)
    raw_payload: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=datetime.now)
