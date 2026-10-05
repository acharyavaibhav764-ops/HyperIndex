from collections.abc import Generator

from sqlalchemy.orm import Session

from db.database import SessionLocal


def get_db() -> Generator[Session, None, None]:
    """Yield a database session and close it after the request finishes."""
    
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()