import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from gyn_kol.database import Base


class Author(Base):
    __tablename__ = "authors"

    author_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name_raw: Mapped[str] = mapped_column(String(500))
    name_normalised: Mapped[str | None] = mapped_column(String(500), index=True)
    affiliation_raw: Mapped[str | None] = mapped_column(String(1000))
    state: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    coauthorships: Mapped[list["Coauthorship"]] = relationship(back_populates="author")


class Paper(Base):
    __tablename__ = "papers"

    paper_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    pmid: Mapped[str | None] = mapped_column(String(20), unique=True, index=True)
    doi: Mapped[str | None] = mapped_column(String(200), index=True)
    title: Mapped[str | None] = mapped_column(String(2000))
    pub_date: Mapped[str | None] = mapped_column(String(20))
    journal: Mapped[str | None] = mapped_column(String(500))
    citation_count: Mapped[int | None] = mapped_column()
    raw_payload: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=datetime.now)

    coauthorships: Mapped[list["Coauthorship"]] = relationship(back_populates="paper")


from gyn_kol.models.coauthorship import Coauthorship  # noqa: E402
