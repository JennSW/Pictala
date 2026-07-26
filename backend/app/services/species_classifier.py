"""Strategy B: AI-assisted species identification for uncaptioned photos.

See DESIGN.md section 4 for the full rationale. The short version: this is
deliberately NOT open-set "what bird is this" -- it's a much easier, cheaper
problem, because we constrain the model to the small set of species (~5-15)
that were actually reported on the specific checklist a photo is already
matched to. The model picks from that list (or says "none of these"), with
a confidence score, and the result is a *suggestion* -- nothing gets written
to the database until the user explicitly accepts it (see
app/routers/match.py).

Kept in its own module, separate from matcher.py, on purpose: matcher.py is
the pure, deterministic, no-network layer (Strategy A) that's trivial to
unit test. This file is the opposite -- it makes a real network call to a
hosted vision model -- so the two are easy to point at separately in a code
review as "here's the rule-based part" vs. "here's the AI part."
"""
import base64

import requests

from app.config import settings

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_API_VERSION = "2023-06-01"

# Reasonable default; requests.get on the photo URL will not run forever,
# but a slow home connection or a big original-size image is still normal.
REQUEST_TIMEOUT_SECONDS = 30


class SpeciesClassifierNotConfigured(Exception):
    """Raised when ANTHROPIC_API_KEY isn't set. Callers should treat this
    as "the feature is unavailable," not a real error to log loudly."""


class SpeciesClassifierError(Exception):
    """Raised when the underlying HTTP call to the vision model fails or
    returns something the code doesn't know how to parse."""


def _guess_media_type(content_type: str | None, url: str) -> str:
    if content_type:
        primary = content_type.split(";")[0].strip().lower()
        if primary in ("image/jpeg", "image/png", "image/gif", "image/webp"):
            return primary
    lowered = url.lower()
    if lowered.endswith(".png"):
        return "image/png"
    if lowered.endswith(".gif"):
        return "image/gif"
    if lowered.endswith(".webp"):
        return "image/webp"
    return "image/jpeg"  # Flickr's default photo format, and a safe fallback


def _fetch_image_as_base64(url: str) -> tuple[str, str]:
    """Download the photo and return (base64_data, media_type)."""
    resp = requests.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
    resp.raise_for_status()
    media_type = _guess_media_type(resp.headers.get("Content-Type"), url)
    return base64.b64encode(resp.content).decode("ascii"), media_type


SUGGEST_TOOL = {
    "name": "report_species_guess",
    "description": (
        "Report which one of the candidate species (if any) the photo most "
        "likely shows."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "common_name": {
                "type": "string",
                "description": (
                    "The candidate common name that best matches the bird in "
                    "the photo, copied exactly from the candidate list, or "
                    "the literal string \"none\" if no candidate plausibly "
                    "matches (e.g. no bird visible, or it's clearly a "
                    "different species than all candidates)."
                ),
            },
            "confidence": {
                "type": "number",
                "description": "Confidence in this guess, from 0.0 to 1.0.",
            },
            "reasoning": {
                "type": "string",
                "description": (
                    "One brief sentence on the visual field marks used "
                    "(size, color pattern, bill shape, etc.) -- shown to the "
                    "user alongside the suggestion so they can judge it "
                    "themselves rather than just trusting a number."
                ),
            },
        },
        "required": ["common_name", "confidence", "reasoning"],
    },
}


def guess_species(photo_url: str, candidate_common_names: list[str]) -> dict:
    """Call the vision model, constrained to `candidate_common_names`.

    Returns {"common_name": str | None, "confidence": float, "reasoning": str}.
    `common_name` is None when the model reports "none" or names something
    outside the candidate list (treated the same way -- the whole point of
    the constraint is that we only ever act on one of the checklist's own
    species, never an open-ended guess).
    """
    if not settings.anthropic_api_key:
        raise SpeciesClassifierNotConfigured(
            "ANTHROPIC_API_KEY is not set in .env -- Strategy B is optional; "
            "see .env.example for how to add it."
        )

    image_b64, media_type = _fetch_image_as_base64(photo_url)

    candidate_list = "\n".join(f"- {name}" for name in candidate_common_names)
    prompt = (
        "This photo was taken during a birdwatching outing where the "
        "following species were reported (in no particular order):\n\n"
        f"{candidate_list}\n\n"
        "Look at the photo and decide which ONE of these species (if any) "
        "it most likely shows. Do not guess a species outside this list -- "
        "if none of them plausibly match what's in the photo (including if "
        "there's no bird clearly visible), report \"none\". Then call the "
        "report_species_guess tool with your answer."
    )

    payload = {
        "model": settings.anthropic_model,
        "max_tokens": 512,
        "tools": [SUGGEST_TOOL],
        "tool_choice": {"type": "tool", "name": "report_species_guess"},
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_b64,
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ],
    }
    headers = {
        "x-api-key": settings.anthropic_api_key,
        "anthropic-version": ANTHROPIC_API_VERSION,
        "content-type": "application/json",
    }

    try:
        resp = requests.post(
            ANTHROPIC_API_URL, json=payload, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        raise SpeciesClassifierError(f"Anthropic API call failed: {exc}") from exc

    tool_use_blocks = [b for b in data.get("content", []) if b.get("type") == "tool_use"]
    if not tool_use_blocks:
        raise SpeciesClassifierError(
            f"Expected a tool_use block in the response, got: {data}"
        )

    result = tool_use_blocks[0].get("input", {})
    common_name = result.get("common_name")
    if not common_name or common_name.strip().lower() == "none":
        common_name = None
    elif common_name not in candidate_common_names:
        # Constrained classification means constrained -- if the model
        # named something outside the candidate list, treat it as "no match"
        # rather than silently accepting an open-set guess.
        common_name = None

    return {
        "common_name": common_name,
        "confidence": float(result.get("confidence", 0.0)),
        "reasoning": result.get("reasoning", ""),
    }
