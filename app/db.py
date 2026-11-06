import os
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import DeclarativeBase, sessionmaker

def database_url():
    host = os.getenv("DB_HOST", "localhost")
    port = os.getenv("DB_PORT", "3050")
    path = os.getenv("DB_PATH", "C:/data/biblioteca.fdb")
    user = os.getenv("DB_USER", "SYSDBA")
    password = os.getenv("DB_PASSWORD", "masterkey")
    if os.getenv("DB_MODE", "server").lower() == "embedded":
        query = {"charset": "UTF8"}
        client = os.getenv("FB_CLIENT_LIBRARY")
        if client:
            query["fb_client_library"] = client.replace("\\", "/")
        return URL.create(
            "firebird+firebird", username=user, host=None,
            database=path.replace("\\", "/"), query=query,
        )
    return URL.create(
        "firebird+firebird", username=user, password=password, host=host,
        port=int(port), database=path.replace("\\", "/"), query={"charset": "UTF8"},
    )

engine = create_engine(database_url(), pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
