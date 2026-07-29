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


class MatchOut(BaseModel):
    photo: PhotoOut
    observation: ObservationOut | None
    method: str
    confidence: float

    model_config = {"from_attributes": True}


class OutingSummary(BaseModel):
    id: int
    location_name: str
    date: str
    species_count: int
    photo_count: int

    model_config = {"from_attributes": True}


class OutingDetail(BaseModel):
    id: int
    location_name: str
    date: str
    latitude: float | None
    longitude: float | None
    observations: list[ObservationOut]
    matches: list[MatchOut]

    model_config = {"from_attributes": True}


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
