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

The three guess_* functions below (constrained, unconstrained, unconstrained
batch) each need a different tool schema and prompt, but the actual
mechanics of calling Anthropic -- build the payload, POST, handle transport
errors, pull the tool_use block out of the response -- were identical three
times over. `_call_anthropic_tool` is that shared mechanic; each function
still owns its own prompt and its own interpretation of the result, since
that's the part that's actually different between them.
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


def _require_configured() -> None:
    if not settings.anthropic_api_key:
        raise SpeciesClassifierNotConfigured(
            "ANTHROPIC_API_KEY is not set in .env -- Strategy B is optional; "
            "see .env.example for how to add it."
        )


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


def _call_anthropic_tool(tool: dict, content: list[dict], max_tokens: int = 512) -> dict:
    """Shared by every guess_* function: build the request, call
    Anthropic, and return the tool_use block's raw `input` dict.
    Validating/extracting fields from that dict stays with each caller
    (different tools have different shapes) -- this only owns the HTTP
    mechanics that used to be copy-pasted three times."""
    payload = {
        "model": settings.anthropic_model,
        "max_tokens": max_tokens,
        "tools": [tool],
        "tool_choice": {"type": "tool", "name": tool["name"]},
        "messages": [{"role": "user", "content": content}],
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
    return tool_use_blocks[0].get("input", {})


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
    _require_configured()
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
    content = [
        {
            "type": "image",
            "source": {"type": "base64", "media_type": media_type, "data": image_b64},
        },
        {"type": "text", "text": prompt},
    ]

    result = _call_anthropic_tool(SUGGEST_TOOL, content)
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


FALLBACK_TOOL = {
    "name": "report_species_guess",
    "description": "Report your best guess for what's shown in the photo.",
    "input_schema": {
        "type": "object",
        "properties": {
            "is_bird": {
                "type": "boolean",
                "description": "Whether the photo clearly shows a bird (as opposed to no bird visible, or an animal that isn't a bird).",
            },
            "common_name": {
                "type": "string",
                "description": (
                    "Your best guess at what's shown, regardless of whether it's a "
                    "bird -- a standard English bird common name if it is one (e.g. "
                    "'Great Blue Heron'), or a plain description of the subject if "
                    "it's not (e.g. 'Dragonfly', 'Squirrel'). Empty string only if "
                    "nothing identifiable is visible at all."
                ),
            },
            "confidence": {
                "type": "number",
                "description": "Confidence in this guess, from 0.0 to 1.0.",
            },
            "reasoning": {
                "type": "string",
                "description": "One brief sentence on the visual field marks used.",
            },
        },
        "required": ["is_bird", "common_name", "confidence", "reasoning"],
    },
}


def guess_species_unconstrained(photo_url: str, title: str | None, tags: str | None) -> dict:
    """Strategy B's fallback path (see docs/USER_STORIES.md, "Species ID
    fallback for eBird gaps"): a photo that doesn't match any reported
    species on its outing -- either because it wasn't logged in eBird at
    all, or because the constrained guess above correctly found no match
    among what *was* reported. This is a deliberate, narrow exception to
    "never do open-set bird ID" (DESIGN.md section 4): it only runs when
    the deterministic and constrained-AI paths have both already failed
    to place the photo, not as a default.

    Returns {"is_bird": bool, "common_name": str | None, "confidence":
    float, "reasoning": str}. Caller is responsible for resolving
    `common_name` against eBird's taxonomy (app/services/ebird_taxonomy)
    -- this function only reports what the model thinks it sees.
    """
    _require_configured()
    image_b64, media_type = _fetch_image_as_base64(photo_url)

    hints = " / ".join(h for h in (title, tags) if h)
    hint_line = f"\n\nThe photo's title/tags (may or may not be useful hints): {hints}" if hints else ""
    prompt = (
        "Identify what's shown in this photo. This photo did not match any "
        "species already reported for this outing, so there's no candidate "
        "list to constrain your guess to -- use your own best judgement. If "
        "it's a bird, give its species. If it's clearly not a bird (e.g. an "
        "insect, mammal, or other subject), still give your best guess at "
        "what it is rather than reporting nothing." + hint_line + "\n\nThen call the "
        "report_species_guess tool with your answer."
    )
    content = [
        {
            "type": "image",
            "source": {"type": "base64", "media_type": media_type, "data": image_b64},
        },
        {"type": "text", "text": prompt},
    ]

    result = _call_anthropic_tool(FALLBACK_TOOL, content)
    return {
        "is_bird": bool(result.get("is_bird", False)),
        "common_name": result.get("common_name") or None,
        "confidence": float(result.get("confidence", 0.0)),
        "reasoning": result.get("reasoning", ""),
    }


# Keeps the prompt (and cost) bounded to an actual "burst," not a whole
# trip in one call -- see issue #5.
MAX_BATCH_SIZE = 10

BATCH_FALLBACK_TOOL = {
    "name": "report_species_guesses",
    "description": "Report your best guess for what's shown in each numbered photo.",
    "input_schema": {
        "type": "object",
        "properties": {
            "guesses": {
                "type": "array",
                "description": "One entry per photo, in the same order the photos were given.",
                "items": {
                    "type": "object",
                    "properties": {
                        "photo_number": {
                            "type": "integer",
                            "description": "The 1-based photo number this guess is for, matching the numbering used in the prompt.",
                        },
                        "is_bird": {
                            "type": "boolean",
                            "description": "Whether the photo clearly shows a bird.",
                        },
                        "common_name": {
                            "type": "string",
                            "description": (
                                "Best guess at what's shown, bird or not -- a standard "
                                "English bird common name if it is one, or a plain "
                                "description otherwise (e.g. 'Dragonfly'). Empty string "
                                "only if nothing identifiable is visible."
                            ),
                        },
                        "confidence": {"type": "number", "description": "0.0 to 1.0."},
                        "reasoning": {
                            "type": "string",
                            "description": "One brief sentence on the visual field marks used for this specific photo.",
                        },
                    },
                    "required": ["photo_number", "is_bird", "common_name", "confidence", "reasoning"],
                },
            },
        },
        "required": ["guesses"],
    },
}


def guess_species_unconstrained_batch(photos: list[dict]) -> list[dict]:
    """Batch version of guess_species_unconstrained -- one Claude call for
    up to MAX_BATCH_SIZE photos instead of one round trip per photo (issue
    #5: a trip with many photos of the same species, e.g. Smith Island's
    Tufted Puffins or a 50+ photo indoor falconry session, was both slow
    one-at-a-time and judged each photo with zero context from its
    neighbors).

    `photos`: list of {"photo_id": int, "url": str, "title": str | None,
    "tags": str | None}. Returns a list of {"photo_id": int, "is_bird":
    bool, "common_name": str | None, "confidence": float, "reasoning":
    str} -- not necessarily one result per input photo (the model can
    skip one), so callers should key off the returned photo_id rather
    than assume positional alignment.
    """
    _require_configured()
    if not photos:
        return []
    if len(photos) > MAX_BATCH_SIZE:
        raise ValueError(f"Batch too large ({len(photos)} photos) -- max is {MAX_BATCH_SIZE}")

    content: list[dict] = []
    for i, photo in enumerate(photos, start=1):
        image_b64, media_type = _fetch_image_as_base64(photo["url"])
        hints = " / ".join(h for h in (photo.get("title"), photo.get("tags")) if h)
        label = f"Photo {i}" + (f" (title/tags: {hints})" if hints else "") + ":"
        content.append({"type": "text", "text": label})
        content.append(
            {
                "type": "image",
                "source": {"type": "base64", "media_type": media_type, "data": image_b64},
            }
        )

    prompt = (
        f"These are {len(photos)} numbered photos from the same birdwatching trip. "
        "For EACH photo, identify what's shown -- if it's a bird, give its species; "
        "if it's clearly not a bird, still give your best guess at what it is rather "
        "than reporting nothing. Judge each photo on its own visual evidence -- they "
        "may show the same species as each other, or different ones. Then call "
        "report_species_guesses with exactly one entry per photo, in order."
    )
    content.append({"type": "text", "text": prompt})

    result = _call_anthropic_tool(BATCH_FALLBACK_TOOL, content, max_tokens=256 * len(photos) + 256)
    guesses = result.get("guesses", [])
    results = []
    for g in guesses:
        idx = g.get("photo_number")
        if not isinstance(idx, int) or not (1 <= idx <= len(photos)):
            continue
        results.append(
            {
                "photo_id": photos[idx - 1]["photo_id"],
                "is_bird": bool(g.get("is_bird", False)),
                "common_name": g.get("common_name") or None,
                "confidence": float(g.get("confidence", 0.0)),
                "reasoning": g.get("reasoning", ""),
            }
        )
    return results
