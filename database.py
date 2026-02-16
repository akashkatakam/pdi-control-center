# database.py
from sqlalchemy import create_engine, event
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import Pool
import os
from typing import Generator
from dotenv import load_dotenv
from utils.logger import setup_logger

# Setup logger for database module
logger = setup_logger("database")

# Load environment variables
load_dotenv()
logger.info("Environment variables loaded")

# --- 1. SECURE CONFIGURATION ---
# Read from environment variables instead of Streamlit secrets
DB_USER = os.getenv("DB_USER")
DB_PASS = os.getenv("DB_PASS")
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT", "3306")
DB_NAME = os.getenv("DB_NAME")

# Log configuration status (without exposing sensitive data)
logger.debug(f"Database configuration - Host: {DB_HOST}, Port: {DB_PORT}, Database: {DB_NAME}, User: {DB_USER}")

# --- 2. DATABASE URL ---
if DB_HOST and DB_USER and DB_PASS and DB_NAME:
    # Standard MySQL/PyMySQL connection string for AWS RDS/Aurora
    SQLALCHEMY_DATABASE_URL = (
        f"mysql+pymysql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    )
    logger.info(f"Using MySQL database at {DB_HOST}:{DB_PORT}/{DB_NAME}")
else:
    # Fallback for local development/testing only
    SQLALCHEMY_DATABASE_URL = "sqlite:///./sales_data_dev.db"
    logger.warning("Database credentials not found in environment. Using SQLite fallback for development")

# --- 3. CREATE ENGINE ---
logger.info("Creating database engine...")
try:
    engine = create_engine(
        SQLALCHEMY_DATABASE_URL,
        pool_pre_ping=True,
        echo=False,  # Set to True for debugging SQL queries
        pool_size=10,  # Maximum number of connections
        max_overflow=20,  # Allow 20 additional connections
        pool_recycle=3600,  # Recycle connections after 1 hour
    )
    logger.info("Database engine created successfully")
    logger.debug(f"Connection pool configured: size=10, max_overflow=20, recycle=3600s")
except Exception as e:
    logger.critical(f"Failed to create database engine: {str(e)}", exc_info=True)
    raise


# Add connection pool event listeners for logging
@event.listens_for(Pool, "connect")
def receive_connect(dbapi_conn, connection_record):
    """Log when a new connection is created"""
    logger.debug("New database connection established")


@event.listens_for(Pool, "checkout")
def receive_checkout(dbapi_conn, connection_record, connection_proxy):
    """Log when a connection is checked out from the pool"""
    logger.debug("Database connection checked out from pool")


@event.listens_for(Pool, "checkin")
def receive_checkin(dbapi_conn, connection_record):
    """Log when a connection is returned to the pool"""
    logger.debug("Database connection returned to pool")


# --- 4. SESSION AND BASE ---
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

logger.info("Database session factory configured")


# Dependency to get the database session (FastAPI compatible)
def get_db() -> Generator:
    """Provides a database session with logging."""
    session_id = id(SessionLocal())  # Generate unique session identifier
    logger.debug(f"Creating database session [ID: {session_id}]")

    db = SessionLocal()

    try:
        logger.debug(f"Database session active [ID: {session_id}]")
        yield db
        logger.debug(f"Database session yielded successfully [ID: {session_id}]")

    except Exception as e:
        logger.error(f"Database session error [ID: {session_id}]: {str(e)}", exc_info=True)
        db.rollback()
        logger.warning(f"Database transaction rolled back [ID: {session_id}]")
        raise

    finally:
        db.close()
        logger.debug(f"Database session closed [ID: {session_id}]")


# Test database connection
def test_connection() -> bool:
    """Test database connectivity with logging"""
    logger.info("Testing database connection...")
    try:
        with engine.connect() as connection:
            connection.execute("SELECT 1")
            logger.info("✅ Database connection test successful")
            return True
    except Exception as e:
        logger.error(f"❌ Database connection test failed: {str(e)}", exc_info=True)
        return False


# Initialize database tables
def init_db():
    """Initialize database tables with logging"""
    logger.info("Initializing database tables...")
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("✅ Database tables initialized successfully")
    except Exception as e:
        logger.error(f"❌ Failed to initialize database tables: {str(e)}", exc_info=True)
        raise


# Log database module initialization
logger.info("Database module initialized successfully")
