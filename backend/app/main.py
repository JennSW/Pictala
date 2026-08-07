from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db import Base, engine, add_missing_columns
from app.routers import outings, sync, match, search, unassigned

Base.metadata.create_all(bind=engine)
add_missing_columns()

app = FastAPI(
    title="BirdTrip API",
    description="Matches your eBird checklists to your Flickr photos, per outing.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # Vite dev server
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(outings.router)
app.include_router(sync.router)
app.include_router(match.router)
app.include_router(search.router)
app.include_router(unassigned.router)


@app.get("/health")
def health():
    return {"status": "ok"}
