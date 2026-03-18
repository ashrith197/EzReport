from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager
import os
import json
import uuid
import pandas as pd
from pathlib import Path
from datetime import datetime

# Local imports
from llm_service import LLMService, ContextManager
from transform import process_and_store_data
from validator import clean_and_parse_json, validate_sql_semantics

# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------
llm_service = None  # Initialize during startup

# Cached at startup
cached_schema: dict = {}
db_path_str: str = ""

# In-memory session store:  session_id -> { context_manager, messages[] }
sessions: Dict[str, Dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# Startup / Shutdown
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load CSV into SQLite and cache schema once at startup."""
    global cached_schema, db_path_str, llm_service

    # Initialize LLM service safely
    try:
        llm_service = LLMService()
        print("[startup] LLMService initialized")
    except Exception as e:
        print(f"[startup] ERROR initializing LLMService: {e}")
        llm_service = None

    # Load CSV and create database
    csv_path = os.getenv("CSV_PATH")
    if csv_path:
        csv_path = Path(csv_path)
    else:
        csv_path = Path(__file__).parent / "data" / "dataset.csv"

    db_path = Path(__file__).parent / "data.db"
    db_path_str = str(db_path)

    try:
        df = pd.read_csv(csv_path)
        cached_schema = process_and_store_data(df, db_path=db_path_str, table_name="data")
        print(f"[startup] Loaded {len(df)} rows from {csv_path}")
        print(f"[startup] Schema: {json.dumps(cached_schema, indent=2)}")
    except Exception as e:
        print(f"[startup] WARNING — failed to load CSV: {e}")

    yield  # app is running


app = FastAPI(title="Chat-Report Generation API", lifespan=lifespan)

# CORS — allow dev servers, ngrok tunnels, and Vercel deployments
ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://localhost:5174",
]

# Allow extra origins via env var (comma-separated) — add your Vercel URL here
extra_origins = os.getenv("ALLOWED_ORIGINS", "")
if extra_origins:
    ALLOWED_ORIGINS.extend([o.strip() for o in extra_origins.split(",") if o.strip()])

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_origin_regex=r"https://(.*\.ngrok-free\.app|.*\.vercel\.app)",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------
class ReportRequest(BaseModel):
    query: str

class ReportResponse(BaseModel):
    description: str
    sql_query: str
    chart_type: str
    warning: Optional[str] = None

class ChatMessageRequest(BaseModel):
    session_id: str
    message: str

class MessageItem(BaseModel):
    role: str          # "user" | "assistant" | "error"
    content: str       # display text
    data: Optional[dict] = None   # structured fields for assistant
    timestamp: Optional[str] = None

class SessionResponse(BaseModel):
    session_id: str
    messages: List[MessageItem]

class ChatMessageResponse(BaseModel):
    session_id: str
    reply: MessageItem


# ---------------------------------------------------------------------------
# Chat session endpoints
# ---------------------------------------------------------------------------
@app.post("/chat/session")
async def create_session():
    """Create a new chat session."""
    session_id = str(uuid.uuid4())
    sessions[session_id] = {
        "context_manager": ContextManager(),
        "messages": [],
        "created_at": datetime.utcnow().isoformat(),
    }
    return {"session_id": session_id}


@app.get("/chat/session/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str):
    """Retrieve all messages in a session."""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found.")
    return SessionResponse(
        session_id=session_id,
        messages=sessions[session_id]["messages"],
    )


@app.post("/chat/message", response_model=ChatMessageResponse)
async def send_chat_message(request: ChatMessageRequest):
    """Send a user message and get an assistant response within a session."""
    sid = request.session_id
    user_text = request.message.strip()

    if not user_text:
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    # Auto-create session if it doesn't exist
    if sid not in sessions:
        sessions[sid] = {
            "context_manager": ContextManager(),
            "messages": [],
            "created_at": datetime.utcnow().isoformat(),
        }

    session = sessions[sid]
    ctx: ContextManager = session["context_manager"]
    now = datetime.utcnow().isoformat()

    # Store user message
    user_msg = MessageItem(role="user", content=user_text, timestamp=now)
    session["messages"].append(user_msg)

    # --- Pipeline: schema → prompt → LLM → parse → validate ---
    try:
        if not cached_schema:
            raise ValueError("Schema not available. Backend may not have loaded the CSV.")

        if llm_service is None:
            raise ValueError("LLM service not initialized. Check API key configuration.")

        schema_str = json.dumps(cached_schema, indent=2)
        past_conversation_str = ctx.get_history_json_str()

        prompt = llm_service.build_prompt(user_text, schema_str, past_conversation_str)
        raw_response = llm_service.generate_response(prompt)

        if not raw_response or raw_response.startswith("Error:"):
            raise ValueError(f"LLM failed: {raw_response}")

        parsed = clean_and_parse_json(raw_response)

        is_valid, sql_msg = validate_sql_semantics(parsed["sql_query"], db_path=db_path_str)
        if not is_valid:
            raise ValueError(f"SQL validation failed: {sql_msg}")

        # Store in context for follow-ups
        ctx.add_interaction(
            user_query=user_text,
            description=parsed["description"],
            sql_query=parsed["sql_query"],
            chart_type=parsed["chart_type"],
        )

        assistant_content = parsed["description"]
        assistant_data = {
            "description": parsed["description"],
            "sql_query": parsed["sql_query"],
            "chart_type": parsed["chart_type"],
            "warning": parsed.get("warning"),
        }

        assistant_msg = MessageItem(
            role="assistant",
            content=assistant_content,
            data=assistant_data,
            timestamp=datetime.utcnow().isoformat(),
        )

    except Exception as e:
        # Return an error message inside the chat — don't crash the session
        assistant_msg = MessageItem(
            role="error",
            content=f"Sorry, I couldn't process that request. {str(e)}",
            timestamp=datetime.utcnow().isoformat(),
        )

    session["messages"].append(assistant_msg)
    return ChatMessageResponse(session_id=sid, reply=assistant_msg)


# ---------------------------------------------------------------------------
# Original endpoints (preserved)
# ---------------------------------------------------------------------------
@app.post("/understand-report", response_model=ReportResponse)
async def understand_report(request: ReportRequest):
    path = os.getenv("CSV_PATH", "data/dataset.csv")
    db_path = Path(__file__).parent / "data.db"

    try:
        df = pd.read_csv(path)
        schema_dict = process_and_store_data(df, db_path=str(db_path), table_name="data")
        schema_str = json.dumps(schema_dict, indent=2)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load dataset and extract schema: {e}")

    # Use global context manager for backward compat
    global_ctx = ContextManager()
    past_conversation_str = global_ctx.get_history_json_str()

    if llm_service is None:
        raise HTTPException(status_code=500, detail="LLM service not initialized. Check API key configuration.")

    prompt = llm_service.build_prompt(request.query, schema_str, past_conversation_str)
    raw_response = llm_service.generate_response(prompt)
    if not raw_response or raw_response.startswith("Error:"):
        raise HTTPException(status_code=500, detail=f"LLM failed to generate a response: {raw_response}")

    try:
        parsed_data = clean_and_parse_json(raw_response)
    except ValueError as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse or validate LLM JSON output: {e}")

    is_valid_sql, sql_msg = validate_sql_semantics(parsed_data["sql_query"], db_path=str(db_path))
    if not is_valid_sql:
        raise HTTPException(status_code=400, detail=f"Generated SQL failed validation: {sql_msg}")

    return parsed_data


class ValidateSqlRequest(BaseModel):
    sql_query: str

@app.get("/schema")
async def get_schema():
    if cached_schema:
        return cached_schema
    path = os.getenv("CSV_PATH", "data/dataset.csv")
    db_path = Path(__file__).parent / "data.db"
    try:
        df = pd.read_csv(path)
        schema_dict = process_and_store_data(df, db_path=str(db_path), table_name="data")
        return schema_dict
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load schema: {e}")

@app.post("/validate-sql")
async def validate_sql_endpoint(request: ValidateSqlRequest):
    db_path = str(Path(__file__).parent / "data.db")
    is_valid, msg = validate_sql_semantics(request.sql_query, db_path=db_path)
    if not is_valid:
        raise HTTPException(status_code=400, detail=msg)
    return {"status": "valid", "message": "SQL query is semantically valid."}

@app.get("/health")
async def health_check():
    return {"status": "ok"}
