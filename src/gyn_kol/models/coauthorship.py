from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from gyn_kol.database import Base


class Coauthorship(Base):
    __tablename__ = "coauthorships"

    author_id: Mapped[str] = mapped_column(String(36), ForeignKey("authors.author_id"), primary_key=True)
    paper_id: Mapped[str] = mapped_column(String(36), ForeignKey("papers.paper_id"), primary_key=True)
    author_position: Mapped[int | None] = mapped_column()

    author: Mapped["Author"] = relationship(back_populates="coauthorships")
    paper: Mapped["Paper"] = relationship(back_populates="coauthorships")


from gyn_kol.models.paper import Author, Paper  # noqa: E402
