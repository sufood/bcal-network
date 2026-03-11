import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, String, Text, func
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import Mapped, mapped_column

from gyn_kol.database import Base


class MbsItem(Base):
    __tablename__ = "mbs_items"

    mbs_item_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    item_number: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(200))
    group: Mapped[str | None] = mapped_column(String(200))
    subgroup: Mapped[str | None] = mapped_column(String(200))
    schedule_fee: Mapped[float | None] = mapped_column(Float)
    benefit_75: Mapped[float | None] = mapped_column(Float)
    benefit_85: Mapped[float | None] = mapped_column(Float)
    gynaecology_relevance: Mapped[str | None] = mapped_column(Text)
    item_start_date: Mapped[str | None] = mapped_column(String(20))
    item_end_date: Mapped[str | None] = mapped_column(String(20))
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=datetime.now)
