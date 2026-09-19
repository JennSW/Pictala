"""Pydantic response/request models -- kept separate from the ORM models
so the API contract can evolve independently of the DB schema."""
from pydantic import BaseModel

from app.config import settings


class ObservationOut(BaseModel):
    id: int
    common_name: str
    scientific_name: str | None
    count: str | None

    model_config = {"from_attributes": True}


class PhotoOut(BaseModel):
    id: int
    flickr_id: str
    title: str | None
    date_taken: str
    url_medium: str | None
    latitude: float | None
    longitude: float | None
    flickr_url: str | None = None

    model_config = {"from_attributes": True}


def photo_out(photo) -> "PhotoOut":
    """Build a PhotoOut with its Flickr display-page link -- not just the
    raw .jpg (see docs/PRD.md Section 4, the photo-linking requirement).
    A plain `from_attributes` mapping can't populate this since it isn't
    a real column on Photo, so callers use this instead of relying on
    automatic nested serialization."""
    flickr_url = (
        f"https://www.flickr.com/photos/{settings.flickr_user_id}/{photo.flickr_id}/"
        if settings.flickr_user_id
        else None
    )
    return PhotoOut(
        id=photo.id,
        flickr_id=photo.flickr_id,
        title=photo.title,
        date_taken=photo.date_taken,
        url_medium=photo.url_medium,
        latitude=photo.latitude,
        longitude=photo.longitude,
        flickr_url=flickr_url,
    )


class TimezoneMismatch(BaseModel):
    """Present only when the photo's camera-recorded UTC offset (EXIF
    `OffsetTimeOriginal`) disagrees with the offset that should actually
    be in effect at the checklist's location/date -- see
    app/services/timezone_check.py (issue #6). `hours_diff` is the
    correction the "adjust" action would apply to `date_taken`."""
    photo_utc_offset: str
    expected_utc_offset: str
    hours_diff: float


class PossibleDuplicate(BaseModel):
    """Flagged by app/services/duplicate_detection.py (issue #39) --
    other photos sharing a normalized title + calendar day, a likely
    signature of a re-exported/re-uploaded duplicate. Detection only,
    no auto-action -- shown so the user can verify/delete on Flickr
    themselves."""
    other_photo_ids: list[int]
    other_flickr_urls: list[str | None]


class MatchOut(BaseModel):
    checklist_id: int | None
    photo: PhotoOut
    observation: ObservationOut | None
    method: str
    confidence: float
    fallback_common_name: str | None = None
    fallback_scientific_name: str | None = None
    note: str | None = None
    ebird_checklist_url: str | None = None
    reviewed_at: str | None = None
    timezone_mismatch: TimezoneMismatch | None = None
    possible_duplicate: PossibleDuplicate | None = None

    model_config = {"from_attributes": True}


def ebird_checklist_url(checklist) -> str:
    """Link to the real checklist on eBird.org -- shown alongside a
    fallback identification so the user can add the species there
    themselves, since BirdTrip never writes back to eBird (see
    docs/USER_STORIES.md, "Species ID fallback for eBird gaps")."""
    return f"https://ebird.org/checklist/{checklist.submission_id}"


class OutingSummary(BaseModel):
    id: int
    location_name: str
    date: str
    species_count: int
    photo_count: int
    reviewed_at: str | None = None

    model_config = {"from_attributes": True}


class PhotoGroups(BaseModel):
    """Grouping data for the outing review UI (issue #43) -- see
    app/services/outing_review.py for the bucket definitions. Exposed
    unconditionally regardless of reviewed state; which buckets a given
    UI shows, and how they're labeled, is a frontend decision."""
    ebird_and_flickr: list[int]
    flickr_best_guess: list[int]
    needs_claude: list[int]
    ebird_no_photo: list[int]


class OutingDetail(BaseModel):
    id: int
    location_name: str
    date: str
    latitude: float | None
    longitude: float | None
    observations: list[ObservationOut]
    matches: list[MatchOut]
    reviewed_at: str | None = None
    photo_groups: PhotoGroups

    model_config = {"from_attributes": True}


class ClusterSummary(BaseModel):
    """A checklist-less photo cluster (see issue #35,
    app/services/photo_clusters.py) -- photos grouped by date + capture-
    time proximity since there's no checklist (and essentially never any
    GPS) to group by instead. `id` is a synthetic string, not a DB row."""
    id: str
    date: str
    photo_count: int


class ClusterDetail(BaseModel):
    id: str
    date: str
    matches: list[MatchOut]


class SpeciesSuggestion(BaseModel):
    """Response from Strategy B's /match/{checklist_id}/suggest/{photo_id}.
    Nothing is persisted yet at this point -- this is just the model's
    guess, for the user to accept or reject."""

    photo_id: int
    checklist_id: int
    candidate_common_names: list[str]
    suggested_observation_id: int | None
    suggested_common_name: str | None
    confidence: float
    reasoning: str


class SearchResult(BaseModel):
    """One row of a species search -- a confirmed photo/species match,
    with enough outing context to navigate back to it (see
    docs/USER_STORIES.md, 'Story: Search by species'). Only confirmed
    matches (Bucket 1) are searchable; unmatched/pending photos aren't
    surfaced here."""

    checklist_id: int
    location_name: str
    date: str
    common_name: str
    photo: PhotoOut


class AcceptSuggestionRequest(BaseModel):
    """Body for POST /match/{checklist_id}/accept/{photo_id} -- the user
    has looked at a SpeciesSuggestion and chosen to accept it."""

    observation_id: int
    confidence: float
    suggested_common_name: str | None = None
    """The suggestion's own common_name, passed through unchanged for AI
    accuracy logging (see AiSuggestionLog) -- accept always keeps
    Claude's suggested species as-is, so this is only ever an "accepted"
    outcome, never "corrected"."""


class AssignSpeciesRequest(BaseModel):
    """Body for POST /match/{checklist_id}/assign/{photo_id} -- the user
    picked one of the outing's own reported species themselves, with no
    AI suggestion behind it (e.g. correcting a false-negative "no
    confident match" result). Distinct from AcceptSuggestionRequest so
    `method` on the resulting Match can honestly read "manual" rather
    than "ai_suggested"."""

    observation_id: int
    note: str | None = None


class FallbackSuggestion(BaseModel):
    """Response from the fallback identification flow -- a photo that
    doesn't match any of the outing's reported species, either because
    there's no checklist for it at all or because the constrained guess
    correctly found nothing among what was reported. Nothing is
    persisted yet; see docs/USER_STORIES.md, "Species ID fallback for
    eBird gaps"."""

    photo_id: int
    checklist_id: int | None
    is_bird: bool
    common_name: str | None
    scientific_name: str | None
    species_code: str | None
    confidence: float
    reasoning: str
    ebird_checklist_url: str | None
    is_other: bool = False
    """True when `common_name` is a real guess (e.g. "Dragonfly") that
    just doesn't resolve against eBird's bird taxonomy -- species_code
    stays null either way, but this is a legitimate "Other" category the
    user can accept or override with their own note, not an error. Only
    true bird-species resolution ever gets a species_code."""


class AcceptFallbackRequest(BaseModel):
    """Body for POST /match/{checklist_id}/accept-fallback/{photo_id}.

    Just a name -- the endpoint resolves it itself (checklist's own
    species, then eBird's full taxonomy, then plain note) rather than
    trusting a scientific_name/species_code supplied by the caller.
    `confidence` is optional context from an AI guess being accepted
    as-is; a human typing a name has no "confidence" to report, so it
    defaults to certain."""

    common_name: str
    confidence: float = 1.0
    ai_suggested_common_name: str | None = None
    """Set only when this save follows an AI fallback guess (single or
    batched) -- the frontend passes through the original suggestion's
    common_name unchanged, so the backend can log whether the final
    answer matches it (accepted) or differs (corrected). Omitted when
    the text was typed from scratch, with no AI guess behind it at all
    -- that case isn't an AI accuracy data point and shouldn't be
    logged as one."""


class RejectSuggestionRequest(BaseModel):
    """Body for POST /match/{checklist_id}/reject/{photo_id} -- the user
    looked at a constrained SpeciesSuggestion and said no. Nothing about
    the Match row changes (there was nothing to undo, per match.py), but
    the rejection itself is worth recording for AI accuracy tracking."""

    suggested_common_name: str | None
    confidence: float


class AiAccuracyBucket(BaseModel):
    """One accuracy count/percentage breakdown -- either overall, or for
    a single suggestion kind. See AiAccuracyStats.by_kind."""

    total: int
    accepted: int
    corrected: int
    rejected: int
    accuracy: float | None
    """accepted / total, or null if total is 0 -- avoids a division by
    zero reading as a real 0% for a project with no data logged yet."""


class AiAccuracyStats(AiAccuracyBucket):
    """Response for GET /stats/ai-accuracy. Extends the overall bucket
    with the same breakdown per suggestion kind ("constrained" /
    "unconstrained") -- see AiSuggestionLog's docstring for why these
    shouldn't be blended into just the top-level number."""

    by_kind: dict[str, AiAccuracyBucket]
