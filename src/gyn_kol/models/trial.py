import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import Mapped, mapped_column

from gyn_kol.database import Base


class Trial(Base):
    __tablename__ = "trials"

    trial_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    anzctr_id: Mapped[str | None] = mapped_column(String(50), unique=True, index=True)
    nct_id: Mapped[str | None] = mapped_column(String(20), unique=True, index=True)
    title: Mapped[str | None] = mapped_column(String(2000))
    pi_name_raw: Mapped[str | None] = mapped_column(String(500))
    institution: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str | None] = mapped_column(String(100))
    conditions: Mapped[list | None] = mapped_column(JSON)
    raw_payload: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=datetime.now)
