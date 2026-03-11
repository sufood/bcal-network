import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, func
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import Mapped, mapped_column

from gyn_kol.database import Base


class MasterClinician(Base):
    __tablename__ = "master_clinicians"

    clinician_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name_display: Mapped[str | None] = mapped_column(String(500))
    name_normalised: Mapped[str | None] = mapped_column(String(500), index=True)
    primary_institution: Mapped[str | None] = mapped_column(String(500))
    state: Mapped[str | None] = mapped_column(String(50))
    specialty: Mapped[str | None] = mapped_column(String(200))
    source_flags: Mapped[list | None] = mapped_column(JSON)
    pub_count: Mapped[int | None] = mapped_column(Integer, default=0)
    trial_count: Mapped[int | None] = mapped_column(Integer, default=0)
    grant_count: Mapped[int | None] = mapped_column(Integer, default=0)
    review_count: Mapped[int | None] = mapped_column(Integer, default=0)
    h_index_proxy: Mapped[int | None] = mapped_column(Integer)
    influence_score: Mapped[float | None] = mapped_column(Float)
    early_adopter_score: Mapped[float | None] = mapped_column(Float)
    tier: Mapped[int | None] = mapped_column(Integer)
    degree_centrality: Mapped[float | None] = mapped_column(Float)
    betweenness_centrality: Mapped[float | None] = mapped_column(Float)
    clustering_coefficient: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=datetime.now)
