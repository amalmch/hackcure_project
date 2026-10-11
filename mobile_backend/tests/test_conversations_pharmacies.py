import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_get_pharmacies_nearby(client: AsyncClient):
    response = await client.get("/api/v1/pharmacies/nearby", params={
        "lat": 36.8000,
        "lng": 10.1800,
        "radius": 15
    })
    assert response.status_code == 200
    pharmacies = response.json()
    assert len(pharmacies) >= 1
    assert "distance_km" in pharmacies[0]

@pytest.mark.asyncio
async def test_get_conversations_and_send_message(client: AsyncClient, auth_headers):
    headers = await auth_headers(client)
    res = await client.get("/api/v1/conversations", headers=headers)
    assert res.status_code == 200
    convs = res.json()
    assert len(convs) >= 1
    conv_id = convs[0]["id"]

    # Send a new message
    msg_res = await client.post(
        f"/api/v1/conversations/{conv_id}/messages",
        headers=headers,
        json={"content": "Testing real-time healthcare message"}
    )
    assert msg_res.status_code == 200
    assert msg_res.json()["content"] == "Testing real-time healthcare message"

@pytest.mark.asyncio
async def test_get_appointments(client: AsyncClient, auth_headers):
    headers = await auth_headers(client)
    res = await client.get("/api/v1/appointments", headers=headers)
    assert res.status_code == 200
    appts = res.json()
    assert len(appts) >= 1
