"""SQLAlchemy models for AutoPi's durable, structured data.

These sit alongside the JSON state files, not in place of them. Anything
whose shape varies by driver, vehicle, or rule (action params, a profile's
per-vehicle config, a CAN signal's decode definition, a rule's condition
tree) is kept as a JSON column so new fields never require a migration.

Every table carries enough to round-trip through export/import
(``db/importexport.py``) without loss.
"""
from __future__ import annotations

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Action(Base):
    """A DB-backed mirror of an action library entry.

    The live registry (``actions/registry.py``) still reads and writes
    ``actions.json`` today; this table is here so a future switch to a
    DB-backed store (or an external tool) has a stable schema to target, and
    so export/import can carry actions like any other record.
    """

    __tablename__ = "actions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    label: Mapped[str] = mapped_column(String(200), default="")
    driver: Mapped[str] = mapped_column(String(64), default="shell")
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    icon: Mapped[str] = mapped_column(String(100), default="bi-lightning-charge")
    color: Mapped[str] = mapped_column(String(20), default="#334155")
    category: Mapped[str] = mapped_column(String(100), default="Actions")
    members: Mapped[list] = mapped_column(JSON, default=list)
    deck_only: Mapped[bool] = mapped_column(Boolean, default=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "driver": self.driver,
            "params": self.params or {},
            "icon": self.icon,
            "color": self.color,
            "category": self.category,
            "members": self.members or [],
            "deck_only": self.deck_only,
        }


class Profile(Base):
    """A vehicle profile: which vehicle a saved config applies to."""

    __tablename__ = "profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    make: Mapped[str] = mapped_column(String(100), default="")
    model: Mapped[str] = mapped_column(String(100), default="")
    vin: Mapped[str] = mapped_column(String(32), default="")
    config: Mapped[dict] = mapped_column(JSON, default=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "year": self.year,
            "make": self.make,
            "model": self.model,
            "vin": self.vin,
            "config": self.config or {},
        }


class CanMessage(Base):
    """A known CAN message: an arbitration id and the signals packed into it."""

    __tablename__ = "can_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    arbitration_id: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(200), default="")
    is_fd: Mapped[bool] = mapped_column(Boolean, default=False)

    # No delete-orphan here on purpose: import upserts signals one at a time
    # by id and must never drop a signal just because a given import payload
    # did not happen to mention it. Deleting a message still cascades to its
    # signals through the database foreign key (ondelete="CASCADE").
    signals: Mapped[list["CanSignal"]] = relationship(
        back_populates="message", cascade="save-update, merge", passive_deletes=True,
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "arbitration_id": self.arbitration_id,
            "name": self.name,
            "is_fd": self.is_fd,
            "signals": [s.to_dict() for s in self.signals],
        }


class CanSignal(Base):
    """A single signal decoded out of a CAN message's data bytes.

    Kept minimal on purpose: the decode details (start bit, length,
    byte order, scale, offset, unit) live in ``definition`` so new decode
    rules do not need a schema change.
    """

    __tablename__ = "can_signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_id: Mapped[int] = mapped_column(
        ForeignKey("can_messages.id", ondelete="CASCADE"), nullable=False,
    )
    name: Mapped[str] = mapped_column(String(200), default="")
    definition: Mapped[dict] = mapped_column(JSON, default=dict)

    message: Mapped[CanMessage] = relationship(back_populates="signals")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "definition": self.definition or {},
        }


class LogicRule(Base):
    """A user-defined automation rule (condition/action tree kept as JSON)."""

    __tablename__ = "logic_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    definition: Mapped[dict] = mapped_column(JSON, default=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "definition": self.definition or {},
        }
