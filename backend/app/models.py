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

    outing_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    """Stored, explicit "this outing has been reviewed" state (issue
    #43) -- deliberately a real column, not computed live from whether
    any photos still need review, per Jen's call: this is likely to
    anchor a future feature (the saved/locked-day concept from #11),
    and a stored flag is one less thing to recompute wherever that
    matters. There's no real Outing table (outings are computed groups
    of checklists -- see app/services/outing_grouping.py), so this is
    only ever meaningful on the group's *primary* checklist (the same
    one whose id already serves as the outing's canonical id
    elsewhere, e.g. in outings.py's list_outings) -- other members of
    the group leave this null."""


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
    utc_offset: Mapped[str | None] = mapped_column(String, nullable=True)
    """The camera's recorded UTC offset at capture time (e.g. "-08:00"),
    from EXIF `OffsetTimeOriginal` (falling back to `OffsetTime`) --
    see app/services/flickr_exif.py. Null means either not fetched yet
    or the photo's EXIF simply doesn't have it (not every camera writes
    this tag). Powers the timezone-mismatch check (issue #6): compare
    against the checklist location's *actual* offset on that date to
    catch a camera clock that was never updated while traveling."""
    duplicate_group_key: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    """Set at sync time by app/services/duplicate_detection.py, not
    computed live -- duplicate detection needs a full-library scan to
    find matches, which is wasted work to repeat on every outing/cluster
    page load. Computed once per sync instead and stored here, so a page
    load just does an indexed `WHERE duplicate_group_key = ?` instead of
    re-scanning every photo. Two photos are duplicates of each other iff
    they share the same non-null value here -- the value itself is the
    heuristic's own group identity (stripped title + calendar day), not
    an arbitrary id, so no separate lookup table is needed. Null means
    not currently flagged as part of a duplicate group."""

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
    checklist_id: Mapped[int | None] = mapped_column(
        ForeignKey("checklists.id"), nullable=True
    )
    """Null means this photo has no eBird checklist at all -- either
    permanently (e.g. a captive/indoor bird photo that will never be a
    countable eBird sighting) or just not yet (a real outing whose
    checklist hasn't been uploaded). Deliberately null, not a sentinel
    id like 0: a real FK constraint already supports "no reference"
    cleanly, and null can never be mistaken for a real checklist by
    code that forgets a special-case rule. See
    app/services/photo_clusters.py for how these get surfaced in the
    UI, grouped by date since there's no checklist to group by."""
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
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    """Set the moment a person actually looked at this specific match and
    agreed with what they see -- i.e. accepted an AI suggestion, manually
    assigned it, or accepted/wrote a fallback identification. Null means
    nobody has: rule-based matches are created automatically and start
    unreviewed, since the matcher's own judgment isn't a person's. Powers
    the New/Needs review distinction (docs/USER_STORIES.md) and the
    per-photo fix action -- see issue #32."""

    checklist: Mapped["Checklist"] = relationship(back_populates="matches")
    photo: Mapped["Photo"] = relationship(back_populates="matches")


class SyncLog(Base):
    """One row per manual "Sync" button press (see /sync/run) -- used
    purely to enforce the daily manual-sync limit from docs/USER_STORIES.md's
    Sync spec (never actually built until now). `triggered_at` is local
    time, not UTC, since "day" means the user's own calendar day and this
    is a single-user app running on their own machine -- there's no
    separate server timezone to reconcile."""

    __tablename__ = "sync_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    triggered_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
