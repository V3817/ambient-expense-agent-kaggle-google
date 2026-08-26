import os
import json
import logging
from typing import Any, Optional
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import vertexai
from google.adk.sessions.vertex_ai_session_service import VertexAiSessionService

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("submission_frontend")

app = FastAPI(title="Manager Approval Dashboard")

# Setup templates relative to this file
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

# Read environment variables
PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT")
LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
AGENT_RUNTIME_ID = os.environ.get("AGENT_RUNTIME_ID") or os.environ.get("GOOGLE_CLOUD_AGENT_ENGINE_ID")

# Extract the short ID if the full resource name was provided
agent_engine_id_short = AGENT_RUNTIME_ID
if AGENT_RUNTIME_ID and "/" in AGENT_RUNTIME_ID:
    agent_engine_id_short = AGENT_RUNTIME_ID.split("/")[-1]

logger.info(f"Initializing dashboard backend with Project: {PROJECT_ID}, Location: {LOCATION}, Agent Runtime ID (Short): {agent_engine_id_short}")

# Initialize the Vertex AI Session Service if variables are set
session_service = None
if PROJECT_ID and agent_engine_id_short:
    session_service = VertexAiSessionService(
        project=PROJECT_ID,
        location=LOCATION,
        agent_engine_id=agent_engine_id_short,
    )
else:
    logger.warning("Missing GOOGLE_CLOUD_PROJECT or AGENT_RUNTIME_ID/GOOGLE_CLOUD_AGENT_ENGINE_ID. Session operations will not be available.")


class ActionPayload(BaseModel):
    approved: bool
    interrupt_id: str
    user_id: Optional[str] = "default-user"


@app.get("/", response_class=HTMLResponse)
async def get_dashboard(request: Request):
    """Serves the beautiful, interactive manager dashboard HTML page."""
    try:
        return templates.TemplateResponse(request=request, name="dashboard.html")
    except TypeError:
        return templates.TemplateResponse("dashboard.html", {"request": request})


@app.get("/api/pending")
async def get_pending_approvals():
    """Queries the ADK VertexAiSessionService to list all sessions,

    fetches the full history for each session, and identifies unresolved
    `adk_request_input` function call events.
    """
    if not session_service:
        raise HTTPException(
            status_code=500,
            detail="Vertex AI Session Service is not configured. Please set GOOGLE_CLOUD_PROJECT and AGENT_RUNTIME_ID."
        )

    try:
        # 1. List all sessions for the app "expense_agent"
        list_resp = await session_service.list_sessions(app_name="expense_agent")
        
        pending_list = []

        # 2. For each session, fetch full history to identify unresolved adk_request_input calls
        for session_summary in list_resp.sessions:
            try:
                session = await session_service.get_session(
                    app_name="expense_agent",
                    user_id=session_summary.user_id,
                    session_id=session_summary.id
                )
                if not session or not session.events:
                    continue

                unresolved_calls = {}

                # Scan events to find any function_call for "adk_request_input"
                # and check if there is a subsequent matching function_response
                for event in session.events:
                    if not event.content or not event.content.parts:
                        continue

                    for part in event.content.parts:
                        part_dict = part if isinstance(part, dict) else part.model_dump()

                        # Check for function call requesting input
                        func_call = part_dict.get("function_call")
                        if func_call and func_call.get("name") == "adk_request_input":
                            call_id = func_call.get("id")
                            unresolved_calls[call_id] = {
                                "interrupt_id": call_id,
                                "message": func_call.get("args", {}).get("message", ""),
                                "timestamp": event.timestamp,
                            }

                        # Check for function response resolving the input
                        func_resp = part_dict.get("function_response")
                        if func_resp and func_resp.get("name") == "adk_request_input":
                            resp_id = func_resp.get("id")
                            if resp_id in unresolved_calls:
                                unresolved_calls.pop(resp_id)

                # If there are unresolved calls, collect details and risk assessment
                if unresolved_calls:
                    # Extract the risk assessment from the session events if present
                    risk_assessment = None
                    for event in session.events:
                        if event.author == "risk_analyzer" and event.content and event.content.parts:
                            for part in event.content.parts:
                                part_dict = part if isinstance(part, dict) else part.model_dump()
                                text = part_dict.get("text")
                                if text:
                                    try:
                                        risk_assessment = json.loads(text)
                                        break
                                    except Exception:
                                        pass
                            if risk_assessment:
                                break

                    # Add each unresolved interrupt to the pending list
                    for call_id, call_info in unresolved_calls.items():
                        pending_list.append({
                            "session_id": session.id,
                            "user_id": session.user_id,
                            "interrupt_id": call_id,
                            "expense": session.state.get("expense", {}),
                            "message": call_info["message"],
                            "risk_assessment": risk_assessment,
                            "timestamp": call_info["timestamp"],
                        })

            except Exception as e:
                logger.error(f"Error processing session {session_summary.id}: {e}", exc_info=True)

        # Sort pending approvals by timestamp (oldest first)
        pending_list.sort(key=lambda x: x["timestamp"])
        return pending_list

    except Exception as e:
        logger.error(f"Failed to list pending approvals: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/action/{session_id}")
async def submit_action(session_id: str, payload: ActionPayload):
    """Resumes the paused session on Agent Runtime with the manager's decision."""
    if not PROJECT_ID or not AGENT_RUNTIME_ID:
        raise HTTPException(
            status_code=500,
            detail="Vertex AI Agent Runtime is not configured. Please set GOOGLE_CLOUD_PROJECT and AGENT_RUNTIME_ID."
        )

    try:
        # Initialize Vertex AI
        vertexai.init(project=PROJECT_ID, location=LOCATION)

        # Get the agent engine using the vertexai Client
        client = vertexai.Client(project=PROJECT_ID, location=LOCATION)
        agent = client.agent_engines.get(name=AGENT_RUNTIME_ID)

        # Construct the resume payload directly as the dict value of the message argument
        message_payload = {
            "role": "user",
            "parts": [
                {
                    "function_response": {
                        "id": payload.interrupt_id,
                        "name": "adk_request_input",
                        "response": {
                            "decision": "yes" if payload.approved else "no"
                        }
                    }
                }
            ]
        }

        user_id = payload.user_id or "default-user"
        logger.info(f"Resuming session {session_id} on Agent Runtime for user {user_id} with decision: {payload.approved}")

        # Execute the query to resume using the internal stream_query endpoint.
        response_iterator = client.agent_engines._stream_query(
            name=AGENT_RUNTIME_ID,
            config={
                "class_method": "async_stream_query",
                "input": {
                    "user_id": user_id,
                    "session_id": session_id,
                    "message": message_payload
                }
            }
        )

        # Consume the generator to ensure execution completes
        responses = []
        for chunk in response_iterator:
            if hasattr(chunk, "body"):
                responses.append(chunk.body)
            else:
                responses.append(str(chunk))

        logger.info(f"Session {session_id} resumed successfully. Response events: {len(responses)}")
        return {"status": "success", "responses_count": len(responses)}

    except Exception as e:
        logger.error(f"Failed to resume session {session_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8081)
