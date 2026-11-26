import secrets
import time


def create_event_identifier() -> str:
    timestamp_hex = format(int(time.time() * 1000), "x")
    random_suffix = secrets.token_hex(4)
    return f"event_{timestamp_hex}_{random_suffix}"


def create_session_token() -> str:
    return secrets.token_hex(16)
