"""What a failure looks like to a person using Pictala.

Every error the API returns has the same shape:

    {"detail": "what happened, in plain words",
     "hint":   "what to try next, or null",
     "error_id": "short reference for the log, only for unexpected errors"}

The web page shows `detail` and `hint` as they come, so the wording here is what a
person reads. Three rules:

  1. Say what happened in plain words, not what the code did.
  2. When there is something the person can do about it, say what.
  3. Never show a traceback. Unexpected errors get a short `error_id`; the full
     traceback is written to the log under that same id.

Why a middleware and not just an exception handler: Starlette's catch-all 500 handler
sits *outside* the CORS middleware, so a plain 500 reaches the browser without CORS
headers, the browser hides it, and the page can only say "failed to fetch". Here the
error middleware is installed *inside* CORS (see main.py), so even unexpected errors
come back readable.
"""
import logging
import uuid

import requests
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, OperationalError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware

log = logging.getLogger("pictala")


class PictalaError(Exception):
    """An error with a message and, ideally, a next step for the person reading it."""

    status_code = 500

    def __init__(self, message: str, hint: str | None = None, *, status_code: int | None = None):
        super().__init__(message)
        self.message = message
        self.hint = hint
        if status_code is not None:
            self.status_code = status_code


class NotConfiguredError(PictalaError):
    """A feature needs a key or account the person hasn't set up yet."""

    status_code = 400


class BadInputError(PictalaError):
    """The request or uploaded file isn't something the app can use."""

    status_code = 400


class ExternalServiceError(PictalaError):
    """An outside service (Flickr, eBird, Anthropic) failed or refused the request."""

    status_code = 502


def error_body(detail: str, hint: str | None = None, error_id: str | None = None) -> dict:
    return {"detail": detail, "hint": hint, "error_id": error_id}


def _new_error_id() -> str:
    return uuid.uuid4().hex[:8]


async def _pictala_error_handler(_request: Request, exc: PictalaError):
    return JSONResponse(error_body(exc.message, exc.hint), status_code=exc.status_code)


async def _http_exception_handler(_request: Request, exc: StarletteHTTPException):
    detail = exc.detail if isinstance(exc.detail, str) else "The request could not be completed."
    return JSONResponse(error_body(detail), status_code=exc.status_code, headers=getattr(exc, "headers", None))


async def _validation_handler(_request: Request, exc: RequestValidationError):
    problems = []
    for item in exc.errors():
        where = ".".join(str(p) for p in item.get("loc", []) if p not in ("body", "query", "path"))
        problems.append(f"{where}: {item.get('msg')}" if where else str(item.get("msg")))
    return JSONResponse(
        error_body(
            "That request wasn't valid (" + "; ".join(problems[:3]) + ").",
            "This usually means the page and the server are out of step, for example after an "
            "update. Reload the page. If it keeps happening, it is a bug worth reporting.",
        ),
        status_code=422,
    )


def _describe(exc: Exception) -> tuple[int, str, str | None, bool]:
    """(status, detail, hint, is_unexpected) for an exception nothing else handled."""
    if isinstance(exc, requests.exceptions.Timeout):
        return (
            503,
            "An outside service (Flickr, eBird or Anthropic) took too long to respond.",
            "Try again in a moment. If it keeps happening, the service may be having trouble.",
            False,
        )
    if isinstance(exc, requests.exceptions.ConnectionError):
        return (
            503,
            "Couldn't reach an outside service (Flickr, eBird or Anthropic).",
            "Check your internet connection and try again.",
            False,
        )
    if isinstance(exc, requests.exceptions.HTTPError):
        status = getattr(getattr(exc, "response", None), "status_code", None)
        return (
            502,
            f"An outside service refused the request{f' (HTTP {status})' if status else ''}.",
            "If you have added API keys to backend/.env, check they are correct and then restart "
            "the backend. Otherwise try again in a moment.",
            False,
        )
    if isinstance(exc, OperationalError):
        return (
            503,
            "The database is busy or unavailable.",
            "Close any other program that has backend/birdtrip.db open and try again.",
            True,
        )
    if isinstance(exc, IntegrityError):
        return (
            409,
            "That change conflicts with data that is already saved.",
            "Reload the page and try again. If it keeps happening, it is a bug worth reporting.",
            True,
        )
    return (
        500,
        "Something went wrong on the server.",
        "Try again. If it keeps happening, look in backend.log (or the terminal running the backend) for the line with this "
        "reference, and include it if you report the problem.",
        True,
    )


class ErrorBoundaryMiddleware(BaseHTTPMiddleware):
    """Turns any exception nothing else handled into a readable JSON error."""

    async def dispatch(self, request: Request, call_next):
        try:
            return await call_next(request)
        except Exception as exc:  # noqa: BLE001 - this is the catch-all by design
            status, detail, hint, unexpected = _describe(exc)
            error_id = _new_error_id() if unexpected else None
            if unexpected:
                log.error("Unhandled error [%s] on %s %s", error_id, request.method, request.url.path, exc_info=exc)
            else:
                log.warning("%s on %s %s: %s", type(exc).__name__, request.method, request.url.path, exc)
            return JSONResponse(error_body(detail, hint, error_id), status_code=status)


def install_error_handling(app: FastAPI) -> None:
    """Register the handlers and the catch-all middleware.

    Call this BEFORE adding CORSMiddleware: Starlette puts the most recently added
    middleware on the outside, and CORS has to wrap this one so that error responses
    carry CORS headers too.
    """
    app.add_exception_handler(PictalaError, _pictala_error_handler)
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)
    app.add_exception_handler(RequestValidationError, _validation_handler)
    app.add_middleware(ErrorBoundaryMiddleware)
