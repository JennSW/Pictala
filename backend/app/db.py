from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from app.config import settings

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if "sqlite" in settings.database_url else {},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def add_missing_columns():
    """No migration tool (Alembic, etc.) in this project yet -- a single
    SQLite file for one local user hasn't needed one. `create_all()` only
    creates tables that don't exist yet, not columns added to a model
    after its table was already created, so a small guarded ALTER TABLE
    covers that gap for now. Call after `Base.metadata.create_all()`.
    The first real schema churn beyond simple additive columns is the
    signal to introduce Alembic properly instead of growing this."""
    inspector = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not inspector.has_table(table.name):
                continue  # brand new table, create_all already has it
            existing_columns = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name not in existing_columns:
                    col_type = column.type.compile(dialect=engine.dialect)
                    conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {col_type}'))

            existing_indexes = {ix["name"] for ix in inspector.get_indexes(table.name)}
            for index in table.indexes:
                if index.name not in existing_indexes:
                    index.create(bind=conn)
