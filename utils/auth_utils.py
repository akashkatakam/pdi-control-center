# utils/auth_utils.py
# Adapted for FastAPI from Streamlit version

from sqlalchemy.orm import Session
from models import User, UserSession, Branch
import hashlib
import secrets
from datetime import datetime, timedelta


def create_user_session(db: Session, user_id: int) -> str:
    """Generates a secure token and saves it to DB. Returns the token."""
    token = secrets.token_hex(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    expiry_date = datetime.now() + timedelta(days=7)
    
    new_session = UserSession(
        session_token_hash=token_hash,
        user_id=user_id,
        expiry_date=expiry_date
    )
    db.add(new_session)
    db.commit()
    
    return token


def delete_user_session(db: Session, token: str):
    """Deletes session from DB."""
    if token:
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        db.query(UserSession).filter(UserSession.session_token_hash == token_hash).delete()
        db.commit()


def verify_session_token(db: Session, token: str):
    """Verifies if a session token is valid and returns the associated user."""
    if not token:
        return None
    
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    
    session = db.query(UserSession).filter(
        UserSession.session_token_hash == token_hash
    ).first()
    
    if session and session.expiry_date > datetime.utcnow():
        user = db.query(User).filter(User.id == session.user_id).first()
        return user
    
    # Clean up expired session
    if session:
        db.delete(session)
        db.commit()
    
    return None


def get_branch_name(db: Session, branch_id: str) -> str:
    """Get branch name from branch ID."""
    if not branch_id:
        return "All Branches"
    branch = db.query(Branch).filter(Branch.Branch_ID == branch_id).first()
    return branch.Branch_Name if branch else "N/A"
