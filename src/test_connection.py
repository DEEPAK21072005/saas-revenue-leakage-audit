"""
Standalone PostgreSQL ledger connection verification script.
Loads environment configuration from .env, establishes an engine connection via SQLAlchemy,
queries `SELECT version();`, and prints the PostgreSQL version string.
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

def main() -> None:
    # Resolve project root and load environment variables
    project_root = Path(__file__).resolve().parent.parent
    env_path = project_root / ".env"
    
    if env_path.exists():
        load_dotenv(dotenv_path=env_path)
    else:
        load_dotenv()

    db_host = os.getenv("DB_HOST", "localhost")
    db_port = os.getenv("DB_PORT", "5432")
    db_name = os.getenv("DB_NAME", "saas_revenue")
    db_user = os.getenv("DB_USER", "postgres")
    db_pass = os.getenv("DB_PASS", "")

    # Construct SQLAlchemy connection URL
    database_url = f"postgresql+psycopg2://{db_user}:{db_pass}@{db_host}:{db_port}/{db_name}"

    print(f"Connecting to PostgreSQL ledger at {db_host}:{db_port}/{db_name} as user '{db_user}'...")

    try:
        engine = create_engine(database_url, pool_pre_ping=True)
        with engine.connect() as connection:
            result = connection.execute(text("SELECT version();"))
            version_str = result.scalar()
            print("Successfully connected to PostgreSQL ledger!")
            print(f"PostgreSQL Engine Version: {version_str}")
        sys.exit(0)
    except Exception as exc:
        print(f"Connection failed: {exc}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
