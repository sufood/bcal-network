import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import Mapped, mapped_column

from gyn_kol.database import Base


class Grant(Base):
    __tablename__ = "grants"

    grant_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    nhmrc_id: Mapped[str | None] = mapped_column(String(50), unique=True, index=True)
    recipient_name_raw: Mapped[str | None] = mapped_column(String(500))
    institution: Mapped[str | None] = mapped_column(String(500))
    amount: Mapped[int | None] = mapped_column(Integer)
    year: Mapped[int | None] = mapped_column(Integer)
    keywords: Mapped[list | None] = mapped_column(JSON)
    raw_payload: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=datetime.now)
