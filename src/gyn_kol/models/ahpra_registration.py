import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import Mapped, mapped_column

from gyn_kol.database import Base


class AhpraRegistration(Base):
    __tablename__ = "ahpra_registrations"

    registration_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name_raw: Mapped[str] = mapped_column(String(500))
    name_normalised: Mapped[str | None] = mapped_column(String(500), index=True)
    registration_number: Mapped[str | None] = mapped_column(String(50), unique=True, index=True)
    profession: Mapped[str | None] = mapped_column(String(200))
    registration_type: Mapped[str | None] = mapped_column(String(100))
    registration_status: Mapped[str | None] = mapped_column(String(100))
    specialty: Mapped[str | None] = mapped_column(String(200))
    state: Mapped[str | None] = mapped_column(String(50), index=True)
    search_profession: Mapped[str | None] = mapped_column(String(200))
    search_state: Mapped[str | None] = mapped_column(String(50))
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=datetime.now)
