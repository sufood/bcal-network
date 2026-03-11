import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from gyn_kol.database import Base


class ClinicianSourceLink(Base):
    __tablename__ = "clinician_source_links"
    __table_args__ = (
        UniqueConstraint("clinician_id", "source", "source_record_id", name="uq_clinician_source_record"),
    )

    link_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    clinician_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("master_clinicians.clinician_id"), nullable=False, index=True,
    )
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    source_record_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    name_raw: Mapped[str | None] = mapped_column(String(500))
    name_normalised: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
