from pydantic import BaseModel


class MediaAttachment(BaseModel):
    url: str | None = None
    base64_data: str | None = None
    mime_type: str | None = None
    file_name: str | None = None


class SendTextMessageRequest(BaseModel):
    session_name: str = "default"
    recipient_chat_id: str
    message_text: str
    reply_to_message_id: str | None = None


class SendMediaMessageRequest(BaseModel):
    session_name: str = "default"
    recipient_chat_id: str
    attachment: MediaAttachment
    caption: str | None = None
    reply_to_message_id: str | None = None


class SendReactionRequest(BaseModel):
    session_name: str = "default"
    message_id: str
    emoji: str


class SendPresenceRequest(BaseModel):
    session_name: str = "default"
    recipient_chat_id: str
    presence_state: str


class SendPollRequest(BaseModel):
    session_name: str = "default"
    recipient_chat_id: str
    poll_question: str
    poll_options: list[str]
    allow_multiple_answers: bool = False


class CastPollVoteRequest(BaseModel):
    session_name: str = "default"
    recipient_chat_id: str
    poll_message_id: str
    selected_options: list[str]


class DeleteMessageRequest(BaseModel):
    session_name: str = "default"
    recipient_chat_id: str
    message_id: str
    delete_for_everyone: bool = True  # True = delete for both/everyone; False = delete only for me
