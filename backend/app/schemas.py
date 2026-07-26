"""Pydantic response/request models -- kept separate from the ORM models
so the API contract can evolve independently of the DB schema."""
from pydantic import BaseModel


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

    model_config = {"from_attributes": True}


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


class AcceptSuggestionRequest(BaseModel):
    """Body for POST /match/{checklist_id}/accept/{photo_id} -- the user
    has looked at a SpeciesSuggestion and chosen to accept it."""

    observation_id: int
    confidence: float
