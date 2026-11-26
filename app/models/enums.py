from enum import Enum


class SessionStatus(str, Enum):
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    SCAN_QR_CODE = "SCAN_QR_CODE"
    WORKING = "WORKING"
    FAILED = "FAILED"


class EventType(str, Enum):
    SESSION_STATUS = "session.status"
    MESSAGE = "message"
    MESSAGE_REACTION = "message.reaction"
    MESSAGE_ACK = "message.ack"
    PRESENCE_UPDATE = "presence.update"


class PresenceState(str, Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    TYPING = "typing"
    RECORDING = "recording"
