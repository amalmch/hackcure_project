from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from app.config import settings
from app.database import engine, Base
import app.models  # Ensure all SQLAlchemy models are registered
from app.api import (
    auth_router,
    patients_router,
    prescriptions_router,
    doses_router,
    sport_router,
    pharmacies_router,
    conversations_router,
    appointments_router,
    medical_records_router,
    notifications_router,
    doctors_router,
    automation_router,
    companion_router,
    sakina_router,
)
from app.websocket.manager import manager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize database tables on startup
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield

app = FastAPI(
    title=settings.PROJECT_NAME,
    version="1.0.0",
    description="Production Healthcare Patient API for HackCure",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register all API routers
app.include_router(auth_router)
app.include_router(patients_router)
app.include_router(prescriptions_router)
app.include_router(doses_router)
app.include_router(sport_router)
app.include_router(pharmacies_router)
app.include_router(conversations_router)
app.include_router(appointments_router)
app.include_router(medical_records_router)
app.include_router(notifications_router)
app.include_router(doctors_router)
app.include_router(automation_router)
app.include_router(companion_router)
app.include_router(sakina_router)

@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str):
    await manager.connect(websocket, user_id)
    try:
        while True:
            data = await websocket.receive_text()
            # Echo heartbeat or custom message handling
            await manager.send_personal_message({"type": "PONG", "payload": data}, user_id)
    except WebSocketDisconnect:
        manager.disconnect(websocket, user_id)

@app.get("/health")
async def health_check():
    return {"status": "ok", "app": settings.PROJECT_NAME, "env": settings.ENVIRONMENT}
