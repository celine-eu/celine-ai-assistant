"""SQLAlchemy ORM models for celine-ai-assistant."""

from __future__ import annotations

from sqlalchemy import BigInteger, ForeignKey, Index, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Conversation(Base):
    __tablename__ = "conversations"

    conversation_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)

    messages: Mapped[list[Message]] = relationship(
        "Message", back_populates="conversation", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("idx_conv_user", "user_id"),)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("conversations.conversation_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[str] = mapped_column(String(256), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)

    conversation: Mapped[Conversation] = relationship(
        "Conversation", back_populates="messages"
    )

    __table_args__ = (Index("idx_msg_conv", "conversation_id"),)


class Attachment(Base):
    __tablename__ = "attachments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    scope: Mapped[str] = mapped_column(String(16), nullable=False)  # 'user' | 'system'
    owner_user_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    uri: Mapped[str] = mapped_column(Text, nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    ocr_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)

    __table_args__ = (
        Index("idx_att_owner", "owner_user_id"),
        Index("idx_att_scope", "scope"),
        Index("idx_att_created", "created_at"),
    )
