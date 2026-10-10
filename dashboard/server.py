"""
HackCure — FastAPI Backend Server
==================================
Serves the monitoring dashboard, handles WebSocket connections,
and provides REST API for demo event triggers.

Usage:
    cd dashboard
    uvicorn server:app --reload --host 0.0.0.0 --port 8000
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

# ─── Logging ───────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("hackcure.server")

# ─── FastAPI App ───────────────────────────────────────────
app = FastAPI(
    title="HackCure Patient Monitoring",
    description="Privacy-preserving AI patient monitoring with 3D digital twin",
    version="1.0.0",
)

# ─── WebSocket Connection Manager ──────────────────────────
class ConnectionManager:
    """Manages WebSocket connections and broadcasts events."""

    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"Client connected. Total: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
        logger.info(f"Client disconnected. Total: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        """Send event to all connected clients."""
        data = json.dumps(message)
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_text(data)
            except Exception:
                disconnected.append(connection)
        for conn in disconnected:
            self.active_connections.remove(conn)


manager = ConnectionManager()

# ─── Patient State Store (Server-Side) ─────────────────────
patients: dict[str, dict[str, Any]] = {
    "patient_01": {
        "patient_id": "patient_01",
        "name": "Patient A",
        "age": 72,
        "room": "101",
        "room_position": {"x": -4.0, "z": -4.0},
        "state": "normal",
        "fall_detected": False,
        "pain_detected": False,
        "confidence": 0.0,
        "last_event_time": None,
        "alert_priority": "none",
        "source": "system",
    },
    "patient_02": {
        "patient_id": "patient_02",
        "name": "Patient B",
        "age": 68,
        "room": "102",
        "room_position": {"x": 4.0, "z": -4.0},
        "state": "normal",
        "fall_detected": False,
        "pain_detected": False,
        "confidence": 0.0,
        "last_event_time": None,
        "alert_priority": "none",
        "source": "system",
    },
    "patient_03": {
        "patient_id": "patient_03",
        "name": "Patient C",
        "age": 81,
        "room": "103",
        "room_position": {"x": -4.0, "z": 4.0},
        "state": "normal",
        "fall_detected": False,
        "pain_detected": False,
        "confidence": 0.0,
        "last_event_time": None,
        "alert_priority": "none",
        "source": "system",
    },
    "patient_04": {
        "patient_id": "patient_04",
        "name": "Patient D",
        "age": 75,
        "room": "104",
        "room_position": {"x": 4.0, "z": 4.0},
        "state": "normal",
        "fall_detected": False,
        "pain_detected": False,
        "confidence": 0.0,
        "last_event_time": None,
        "alert_priority": "none",
        "source": "system",
    },
}

# Event history
event_history: list[dict] = []
MAX_HISTORY = 100

# Current mode
current_mode = {"mode": "demo"}  # "demo" or "real"


# ─── Pydantic Models ──────────────────────────────────────
class DemoEvent(BaseModel):
    patient_id: str
    event_type: str  # "fall", "pain", "fall_and_pain", "recover", "behavioral_risk", "machine_error"
    confidence: float = 0.90
    risk_level: str = "none" # none, low, moderate, high, critical
    risk_score: float = 0.0
    behavior_indicators: list[str] = []
    recommendations: list[str] = []
    machine_type: str = "" # e.g., "IV Pump", "ECG Monitor"
    
class ModeSwitch(BaseModel):
    mode: str  # "demo" or "real"


# ─── Helper: Process Event ────────────────────────────────
async def process_event(
    patient_id: str,
    event_type: str,
    source: str = "demo",
    confidence: float = 0.90,
    risk_level: str = "none",
    risk_score: float = 0.0,
    behavior_indicators: list = None,
    recommendations: list = None,
    machine_type: str = ""
):
    """Update patient state and broadcast to all clients."""
    if patient_id not in patients:
        logger.warning(f"Unknown patient: {patient_id}")
        return

    patient = patients[patient_id]
    now = datetime.now(timezone.utc).isoformat()
    
    behavior_indicators = behavior_indicators or []
    recommendations = recommendations or []

    if event_type == "fall":
        patient["fall_detected"] = True
        patient["pain_detected"] = False
        patient["state"] = "fall_detected"
        patient["alert_priority"] = "critical"
        risk_level = "critical"
        risk_score = max(risk_score, 0.95)
    elif event_type == "pain":
        patient["fall_detected"] = False
        patient["pain_detected"] = True
        patient["state"] = "pain_detected"
        patient["alert_priority"] = "high"
        risk_level = "high" if risk_level == "none" else risk_level
    elif event_type == "fall_and_pain":
        patient["fall_detected"] = True
        patient["pain_detected"] = True
        patient["state"] = "fall_and_pain"
        patient["alert_priority"] = "critical"
        risk_level = "critical"
        risk_score = max(risk_score, 0.95)
    elif event_type == "behavioral_risk":
        # Do not force a fall or pain state, just update risk
        pass
    elif event_type == "recover":
        patient["fall_detected"] = False
        patient["pain_detected"] = False
        patient["machine_error"] = False
        patient["machine_type"] = ""
        patient["state"] = "normal"
        patient["alert_priority"] = "none"
        risk_level = "none"
        risk_score = 0.0
        behavior_indicators = []
        recommendations = []
    elif event_type == "machine_error":
        patient["machine_error"] = True
        patient["machine_type"] = machine_type
        patient["state"] = "machine_error"
        patient["alert_priority"] = "high"
        risk_level = "high" if risk_level == "none" else risk_level
    else:
        logger.warning(f"Unknown event type: {event_type}")
        return

    patient["confidence"] = confidence
    patient["last_event_time"] = now
    patient["source"] = source
    
    # New AI fields
    patient["risk_level"] = risk_level
    patient["risk_score"] = risk_score
    patient["behavior_indicators"] = behavior_indicators
    patient["recommendations"] = recommendations

    # Build event message
    event = {
        "type": "patient_event",
        "patient_id": patient_id,
        "event_type": event_type,
        "source": source,
        "fall_detected": patient["fall_detected"],
        "pain_detected": patient["pain_detected"],
        "state": patient["state"],
        "confidence": confidence,
        "alert_priority": patient["alert_priority"],
        "risk_level": risk_level,
        "risk_score": risk_score,
        "behavior_indicators": behavior_indicators,
        "recommendations": recommendations,
        "machine_error": patient.get("machine_error", False),
        "machine_type": patient.get("machine_type", ""),
        "timestamp": now,
    }

    # Store in history
    event_history.insert(0, event)
    if len(event_history) > MAX_HISTORY:
        event_history.pop()

    # Broadcast
    await manager.broadcast(event)
    logger.info(f"[{source.upper()}] {patient_id}: {event_type} (conf={confidence:.2f}, risk={risk_level})")


# ─── WebSocket Endpoint ───────────────────────────────────
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        # Send initial state to new client
        init_msg = {
            "type": "init",
            "patients": patients,
            "mode": current_mode["mode"],
            "event_history": event_history[:20],
        }
        await websocket.send_text(json.dumps(init_msg))

        # Keep connection alive and handle client messages
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)

            if msg.get("type") == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))

    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        manager.disconnect(websocket)


# ─── REST API ─────────────────────────────────────────────
@app.get("/api/patients")
async def get_patients():
    """Get current state of all patients."""
    return JSONResponse(content=patients)


@app.get("/api/events")
async def get_events():
    """Get recent event history."""
    return JSONResponse(content=event_history[:50])


@app.post("/api/demo/trigger")
async def trigger_demo_event(event: DemoEvent):
    """Trigger a demo event (Scenario B only)."""
    if current_mode["mode"] != "demo":
        return JSONResponse(
            content={"error": "Demo events only allowed in demo mode"},
            status_code=400,
        )
    await process_event(
        patient_id=event.patient_id,
        event_type=event.event_type,
        source="simulation",
        confidence=event.confidence,
        risk_level=event.risk_level,
        risk_score=event.risk_score,
        behavior_indicators=event.behavior_indicators,
        recommendations=event.recommendations,
        machine_type=event.machine_type
    )
    return JSONResponse(content={"status": "ok", "event": event.event_type})


@app.post("/api/demo/reset")
async def reset_demo():
    """Reset all patients to normal state."""
    for pid in patients:
        await process_event(pid, "recover", source="system", confidence=1.0)
    event_history.clear()
    reset_msg = {"type": "reset", "patients": patients}
    await manager.broadcast(reset_msg)
    return JSONResponse(content={"status": "reset"})


@app.post("/api/mode")
async def switch_mode(mode: ModeSwitch):
    """Switch between demo and real mode."""
    if mode.mode not in ("demo", "real"):
        return JSONResponse(
            content={"error": "Mode must be 'demo' or 'real'"},
            status_code=400,
        )
    current_mode["mode"] = mode.mode
    mode_msg = {"type": "mode_change", "mode": mode.mode}
    await manager.broadcast(mode_msg)
    logger.info(f"Mode switched to: {mode.mode}")
    return JSONResponse(content={"status": "ok", "mode": mode.mode})


@app.post("/api/yolo/event")
async def receive_yolo_event(event: DemoEvent):
    """
    Receive real AI detection events from YOLO/Transformer.
    """
    await process_event(
        patient_id=event.patient_id,
        event_type=event.event_type,
        source="ai_pipeline",
        confidence=event.confidence,
        risk_level=event.risk_level,
        risk_score=event.risk_score,
        behavior_indicators=event.behavior_indicators,
        recommendations=event.recommendations,
        machine_type=event.machine_type
    )
    return JSONResponse(content={"status": "ok"})


# ─── Serve Static Files ───────────────────────────────────
static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/")
async def serve_dashboard():
    """Serve the main dashboard page."""
    return FileResponse(str(static_dir / "index.html"))


# ─── Startup ──────────────────────────────────────────────
@app.on_event("startup")
async def startup():
    logger.info("=" * 60)
    logger.info("HackCure Patient Monitoring Server")
    logger.info("Dashboard: http://localhost:8000")
    logger.info("WebSocket: ws://localhost:8000/ws")
    logger.info("=" * 60)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)

