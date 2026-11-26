# WhatsApp API Service

A self-hosted WhatsApp HTTP & WebSocket API service built with **FastAPI**, **Playwright**, and **MongoDB**. Designed for reliable session persistence, inbound rate limiting, and anti-ban outbound message pacing.

## Features

- **Multi-Session Management**: Create, start, stop, delete, and authenticate sessions via QR code.
- **MongoDB Persistence**: Stores session state, authentication backups, and binary media (GridFS) in MongoDB.
- **Real-Time Events**: Stream live events over WebSocket (`/ws`) or forward them to an HTTP webhook (`WAHA_WEBHOOK_URL`).
- **API Key Authentication**: All `/api/*` and `/ws` routes require an `x-api-key` header (or `x-api-key` query parameter). Public health checks (`/health`, `/ping`) remain open.
- **Inbound Rate Limiting**: Sliding-window rate limiter keyed by API key and client IP (`WAHA_RATE_LIMIT_RPM`).
- **Outbound Anti-Ban Queue**: Per-session message queue with randomized pacing delays, typing simulation, and per-minute/per-hour quotas.

## Architecture

```text
app/
├── main.py              # FastAPI app, lifespan hooks, auth & rate-limit middleware
├── config.py            # Pydantic settings loaded from environment / .env
├── api/
│   ├── router.py        # Aggregates /api routers
│   ├── sessions.py      # Session lifecycle & QR auth endpoints
│   ├── chatting.py      # Messaging, media, reactions, polls, queue endpoints
│   ├── chats.py         # Chat history, polls, and message deletion endpoints
│   └── websocket.py     # Real-time WebSocket event stream (/ws)
├── core/
│   ├── session_manager.py
│   ├── whatsapp_driver.py
│   ├── message_queue.py
│   ├── rate_limiter.py
│   └── event_bus.py
├── database/            # Async Motor client, session store, GridFS media store
├── models/              # Pydantic request/response schemas and enums
└── utils/               # Structured logging and identifier helpers
```

## Prerequisites

- Python 3.11+
- MongoDB (local instance or connection string)
- Playwright Chromium browser binaries

## Setup & Running Locally

### 1. Create a Virtual Environment & Install Dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

### 2. Configure Environment Variables

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

Key variables:
- `WAHA_API_KEY`: Secret key required in the `x-api-key` header. Generate a strong random string (e.g., `openssl rand -hex 32`).
- `WAHA_MONGO_URL`: MongoDB connection URI (e.g., `mongodb://localhost:27017`).
- `WAHA_MONGO_DB`: Database name (default: `whatsapp_api`).

### 3. Start the Server

```bash
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 3000
```

## API Reference

All `/api/*` endpoints require `-H "x-api-key: <YOUR_API_KEY>"`.

### Health
| Method | Endpoint | Auth | Description |
| :--- | :--- | :--- | :--- |
| `GET` | `/health` | Public | Service health check |
| `GET` | `/ping` | Public | Returns `"pong"` |

### Sessions (`/api/sessions`)
| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/api/sessions` | List all sessions |
| `GET` | `/api/sessions/{session_name}` | Get session details |
| `POST` | `/api/sessions` | Create a new session |
| `POST` | `/api/sessions/{session_name}/start` | Start a session |
| `POST` | `/api/sessions/{session_name}/stop` | Stop a running session |
| `GET` | `/api/sessions/{session_name}/auth/qr` | Retrieve QR code for authentication |
| `DELETE` | `/api/sessions/{session_name}` | Delete a session |

### Messaging & Queue (`/api`)
| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/api/sendText` | Send a text message (supports `?wait_for_delivery=true`) |
| `POST` | `/api/sendImage` | Send an image |
| `POST` | `/api/sendFile` | Send a file/document |
| `PUT` | `/api/reaction` | React to a message |
| `POST` | `/api/presence` | Update typing/online presence |
| `POST` | `/api/sendPoll` | Send a poll |
| `POST` | `/api/sendPollVote` | Vote in a poll |
| `POST` | `/api/deleteMessage` | Delete a sent message |
| `GET` | `/api/queue/{session_name}` | Inspect outbound queue & rate-limit status |
| `DELETE` | `/api/queue/{session_name}` | Clear pending messages in the queue |

### Chats (`/api/chats`)
| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/api/chats/{session_name}` | List chats for a session |
| `GET` | `/api/chats/{session_name}/{chat_id}/polls` | Get polls & live votes in a chat |
| `GET` | `/api/chats/{session_name}/{chat_id}/messages` | Fetch messages in a chat |
| `DELETE` | `/api/chats/{session_name}/{chat_id}/messages/{message_id}` | Delete a message |

### WebSocket
- `WS /ws?x-api-key=<YOUR_API_KEY>` — Subscribe to real-time session and message events.

## Quick Examples

```bash
# Health check
curl http://localhost:3000/health

# Create and start a session
curl -X POST -H "x-api-key: <YOUR_API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{"session_name": "default", "start_immediately": true}' \
  http://localhost:3000/api/sessions

# Send a queued text message
curl -X POST -H "x-api-key: <YOUR_API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{"session_name": "default", "recipient_chat_id": "1234567890@c.us", "message_text": "Hello!"}' \
  http://localhost:3000/api/sendText
```

## License

This project is licensed under the [MIT License](LICENSE).
