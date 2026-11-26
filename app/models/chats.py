from pydantic import BaseModel


class ChatSummary(BaseModel):
    chat_id: str
    chat_name: str | None = None
    unread_count: int = 0
    last_message_text: str | None = None
    last_message_timestamp: int | None = None


class ChatMessage(BaseModel):
    message_id: str
    sender_id: str
    timestamp: int
    message_text: str | None = None
    message_type: str = "text"  # text, image, poll, poll_vote, etc.
    poll_question: str | None = None
    poll_options: list[str] | None = None
    poll_votes: list[dict] | None = None
    is_deleted: bool = False

