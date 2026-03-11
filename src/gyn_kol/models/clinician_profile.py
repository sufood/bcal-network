import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from gyn_kol.database import Base


class ClinicianProfile(Base):
    __tablename__ = "clinician_profiles"

    profile_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    clinician_id: Mapped[str] = mapped_column(String(36), ForeignKey("master_clinicians.clinician_id"), unique=True)
    profile_summary: Mapped[str | None] = mapped_column(String(5000))
    engagement_approach: Mapped[str | None] = mapped_column(String(5000))
    model_used: Mapped[str | None] = mapped_column(String(100))
    generated_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=datetime.now)
