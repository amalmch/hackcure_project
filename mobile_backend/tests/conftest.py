import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.utils.security import create_access_token

@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac

@pytest.fixture
def auth_headers():
    # Login as patient Mohamed
    async def _get_headers(client: AsyncClient):
        res = await client.post("/api/v1/auth/login", json={
            "email": "mohamed@example.com",
            "password": "Test123!@#"
        })
        token = res.json()["access_token"]
        return {"Authorization": f"Bearer {token}"}
    return _get_headers
