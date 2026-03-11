import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from gyn_kol.database import Base


class RegistrationVerification(Base):
    __tablename__ = "registration_verifications"

    verification_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    canrefer_profile_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("canrefer_profiles.profile_id"), nullable=True
    )
    ahpra_registration_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("ahpra_registrations.registration_id"), nullable=True
    )
    match_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    match_method: Mapped[str | None] = mapped_column(String(50))
    verification_status: Mapped[str | None] = mapped_column(String(50))
    notes: Mapped[str | None] = mapped_column(String(2000))
    verified_by: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=datetime.now)
