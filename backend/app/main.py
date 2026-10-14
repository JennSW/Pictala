from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db import Base, engine, add_missing_columns
from app.errors import install_error_handling
from app.routers import outings, sync, match, search, unassigned, stats

Base.metadata.create_all(bind=engine)
add_missing_columns()

app = FastAPI(
    title="Pictala API",
    description="Matches your eBird checklists to your Flickr photos, per outing.",
    version="0.1.0",
)

# Must come before CORSMiddleware is added: the most recently added middleware is the
# outermost, and CORS has to wrap the error handling so error responses are readable
# by the browser too (see app/errors.py).
install_error_handling(app)

app.add_middleware(
    CORSMiddleware,
    # Both hostnames point at the same Vite dev server, but browsers treat
    # them as different origins for CORS purposes -- localhost vs 127.0.0.1
    # is a common source of a browser-blocked (not server-side) fetch
    # failure depending on which one ends up in the address bar.
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(outings.router)
app.include_router(sync.router)
app.include_router(match.router)
app.include_router(search.router)
app.include_router(unassigned.router)
app.include_router(stats.router)


@app.get("/health")
def health():
    return {"status": "ok"}
