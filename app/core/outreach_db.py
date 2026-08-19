import os
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.getenv("OUTREACH_DATABASE_URL", "sqlite:///data_storage/outreach.db")

# Create parent directories for SQLite if needed
if DATABASE_URL.startswith("sqlite:///"):
    db_path = DATABASE_URL.replace("sqlite:///", "")
    db_dir = os.path.dirname(os.path.abspath(db_path))
    os.makedirs(db_dir, exist_ok=True)

# For SQLite, check_same_thread needs to be False
connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_outreach_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Auto-create SQLite database tables at startup
try:
    from app.models.outreach import EmailAccount, OutreachSettings
    Base.metadata.create_all(bind=engine)
except Exception as e:
    import logging
    logging.getLogger("mapflow_ai.database").error(f"Failed to auto-create outreach SQL tables: {e}")

