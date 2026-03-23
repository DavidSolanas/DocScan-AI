import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: uuid.uuid4().hex
    )
    filename: Mapped[str] = mapped_column(String, nullable=False)
    format: Mapped[str] = mapped_column(String, nullable=False)
    file_path: Mapped[str] = mapped_column(String, nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="uploaded")
    text_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_scanned: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    ocr_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    upload_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    jobs: Mapped[list["Job"]] = relationship(
        "Job", back_populates="document", cascade="all, delete-orphan"
    )
    extraction: Mapped["Extraction | None"] = relationship(
        "Extraction", back_populates="document", uselist=False, cascade="all, delete-orphan"
    )


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: uuid.uuid4().hex
    )
    document_id: Mapped[str] = mapped_column(
        String, ForeignKey("documents.id"), nullable=False
    )
    job_type: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    progress: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    document: Mapped["Document"] = relationship("Document", back_populates="jobs")


class Extraction(Base):
    __tablename__ = "extractions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    document_id: Mapped[str] = mapped_column(String, ForeignKey("documents.id"), unique=True)
    invoice_type: Mapped[str | None] = mapped_column(String, nullable=True)
    invoice_number: Mapped[str | None] = mapped_column(String, nullable=True)
    invoice_series: Mapped[str | None] = mapped_column(String, nullable=True)
    issuer_cif: Mapped[str | None] = mapped_column(String, nullable=True)
    issuer_name: Mapped[str | None] = mapped_column(String, nullable=True)
    recipient_cif: Mapped[str | None] = mapped_column(String, nullable=True)
    recipient_name: Mapped[str | None] = mapped_column(String, nullable=True)
    issue_date: Mapped[str | None] = mapped_column(String, nullable=True)    # ISO 8601
    total_amount: Mapped[str | None] = mapped_column(String, nullable=True)  # string, never float
    currency: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="valid")  # valid|invalid|needs_review
    validation_errors: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON array
    json_path: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
    )

    document: Mapped["Document"] = relationship("Document", back_populates="extraction")


class ChatSession(Base):
    __tablename__ = "chat_sessions"
    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: uuid.uuid4().hex
    )
    document_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("documents.id"), nullable=True
    )
    # Any relationship using document_id / document_id_b must specify
    # foreign_keys=[...] explicitly to avoid SQLAlchemy AmbiguousForeignKeysError.
    document_id_b: Mapped[str | None] = mapped_column(
        String, ForeignKey("documents.id"), nullable=True
    )
    mode: Mapped[str] = mapped_column(String, nullable=False, default="single")
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )
    messages: Mapped[list["ChatMessage"]] = relationship(
        "ChatMessage", back_populates="session", cascade="all, delete-orphan"
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: uuid.uuid4().hex
    )
    session_id: Mapped[str] = mapped_column(
        String, ForeignKey("chat_sessions.id"), nullable=False
    )
    role: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    citations: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    session: Mapped["ChatSession"] = relationship("ChatSession", back_populates="messages")
