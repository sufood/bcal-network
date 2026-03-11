import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from gyn_kol.database import Base


class ClinicianMbs(Base):
    __tablename__ = "clinician_mbs_mappings"

    mapping_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    clinician_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("master_clinicians.clinician_id"), nullable=False,
    )
    mbs_item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("mbs_items.mbs_item_id"), nullable=False,
    )
    relevance_basis: Mapped[str | None] = mapped_column(Text)
    link_method: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=datetime.now)
