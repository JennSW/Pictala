"""SQLAlchemy models.

Schema mirrors the design doc: checklists + observations come from eBird
(via the "Download My Data" CSV), photos come from Flickr, and matches
records the link the matcher (rule-based or AI-assisted) decided on.
"""
from datetime import datetime

from sqlalchemy import String, Integer, Float, DateTime, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Checklist(Base):
    """One eBird checklist. Multiple checklists sharing the same date and
    `location_id` are treated as a single outing -- see
    app/services/outing_grouping.py -- since a real trip often produces
    several separate checklist submissions (e.g. one per species logged
    separately, or one per observer)."""

    __tablename__ = "checklists"

    id: Mapped[int] = mapped_column(primary_key=True)
    submission_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    location_name: Mapped[str] = mapped_column(String)
    location_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    date: Mapped[str] = mapped_column(String)  # ISO date, e.g. 2026-06-14
    start_time: Mapped[str | None] = mapped_column(String, nullable=True)  # HH:MM
    duration_minutes: Mapped[float | None] = mapped_column(Float, nullable=True)

    observations: Mapped[list["Observation"]] = relationship(
        back_populates="checklist", cascade="all, delete-orphan"
    )
    matches: Mapped[list["Match"]] = relationship(
        back_populates="checklist", cascade="all, delete-orphan"
    )


class Observation(Base):
    """One species entry within a checklist."""

    __tablename__ = "observations"

    id: Mapped[int] = mapped_column(primary_key=True)
    checklist_id: Mapped[int] = mapped_column(ForeignKey("checklists.id"))
    common_name: Mapped[str] = mapped_column(String, index=True)
    scientific_name: Mapped[str | None] = mapped_column(String, nullable=True)
    count: Mapped[str | None] = mapped_column(String, nullable=True)  # eBird allows "X" for uncounted

    checklist: Mapped["Checklist"] = relationship(back_populates="observations")


class Photo(Base):
    """One Flickr photo."""

    __tablename__ = "photos"

    id: Mapped[int] = mapped_column(primary_key=True)
    flickr_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    tags: Mapped[str | None] = mapped_column(Text, nullable=True)  # space-separated
    date_taken: Mapped[str] = mapped_column(String, index=True)  # ISO datetime
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    url_medium: Mapped[str | None] = mapped_column(String, nullable=True)

    matches: Mapped[list["Match"]] = relationship(
        back_populates="photo", cascade="all, delete-orphan"
    )


class Match(Base):
    """Photo <-> checklist (and optionally <-> species) link.

    `method` and `confidence` record HOW the match was made, so the UI (and
    an interviewer looking at the data) can tell rule-based matches from
    AI-suggested ones at a glance. Values: rule_based | rule_based_same_day
    | ai_suggested | manual | ai_fallback.

    `observation_id` links to a real eBird-reported species on this
    outing. The `fallback_*` fields are separate and used instead when
    the species was identified via the fallback flow (see
    docs/USER_STORIES.md, "Species ID fallback for eBird gaps") --
    something the photo shows that was never actually reported on any
    checklist in this outing (e.g. a Heron photographed on a
    Starling-only checklist). Deliberately not a second FK to
    Observation, since there usually isn't one: this label lives on the
    photo only and is never written back to eBird today. These fields
    (particularly `fallback_species_code`, eBird's own species
    identifier) are deliberately the right shape to support an eventual
    real eBird write-back later, if that's ever built -- not just a
    display label.
    """

    __tablename__ = "matches"

    id: Mapped[int] = mapped_column(primary_key=True)
    checklist_id: Mapped[int] = mapped_column(ForeignKey("checklists.id"))
    photo_id: Mapped[int] = mapped_column(ForeignKey("photos.id"))
    observation_id: Mapped[int | None] = mapped_column(
        ForeignKey("observations.id"), nullable=True
    )
    method: Mapped[str] = mapped_column(String, default="rule_based")
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    fallback_common_name: Mapped[str | None] = mapped_column(String, nullable=True)
    fallback_scientific_name: Mapped[str | None] = mapped_column(String, nullable=True)
    fallback_species_code: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    checklist: Mapped["Checklist"] = relationship(back_populates="matches")
    photo: Mapped["Photo"] = relationship(back_populates="matches")
