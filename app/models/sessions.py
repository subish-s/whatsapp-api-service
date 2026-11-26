from pydantic import BaseModel
from app.models.enums import SessionStatus


class SessionData(BaseModel):
    session_name: str
    status: SessionStatus
    account_number: str | None = None
    account_name: str | None = None


class CreateSessionRequest(BaseModel):
    session_name: str
    start_immediately: bool = True
