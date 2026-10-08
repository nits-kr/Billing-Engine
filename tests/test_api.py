import pytest
import uuid
from httpx import AsyncClient, ASGITransport
from main import app, lifespan

@pytest.mark.asyncio
async def test_healthcheck():
    """Verify service health endpoint returns 200 OK."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "Enterprise Agentic Billing Engine" in data["service"]

@pytest.mark.asyncio
async def test_order_creation_and_retrieval():
    """Verify order creation and subsequent Cache-Aside retrieval."""
    transport = ASGITransport(app=app)
    async with lifespan(app):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            payload = {
                "user_email": "test.customer@enterprise.com",
                "amount_cents": 8999
            }
            # 1. Create order
            create_res = await client.post("/api/v1/orders/", json=payload)
            assert create_res.status_code == 201
            order = create_res.json()
            order_id = order["order_id"]
            assert order["status"] == "pending"
            assert order["amount_cents"] == 8999

            # 2. Get order (Cache-Aside pattern)
            get_res = await client.get(f"/api/v1/orders/{order_id}")
            assert get_res.status_code == 200
            assert get_res.json()["order_id"] == order_id

@pytest.mark.asyncio
async def test_payment_webhook_idempotency():
    """Verify webhook guarantees idempotency upon duplicate delivery."""
    transport = ASGITransport(app=app)
    async with lifespan(app):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            event_id = f"evt_test_{uuid.uuid4().hex[:8]}"
            order_id = f"ord_test_{uuid.uuid4().hex[:8]}"
            webhook_payload = {
                "event_id": event_id,
                "type": "payment.succeeded",
                "data": {"order_id": order_id}
            }

            # 1st execution: processed successfully
            r1 = await client.post("/api/v1/orders/webhook/payment", json=webhook_payload)
            assert r1.status_code == 200
            assert r1.json()["status"] == "success"

            # 2nd execution with identical event_id: duplicate ignored
            r2 = await client.post("/api/v1/orders/webhook/payment", json=webhook_payload)
            assert r2.status_code == 200
            assert r2.json()["status"] == "ignored"
            assert r2.json()["reason"] == "duplicate_event_already_processed"

@pytest.mark.asyncio
async def test_agent_workflow_execution():
    """Verify Agentic AI workflow returns structured ReAct action responses."""
    transport = ASGITransport(app=app)
    async with lifespan(app):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            query_payload = {"prompt": "Can you help me check if order ord_sample_123 is valid?"}
            response = await client.post("/api/v1/orders/agent/execute", json=query_payload)
            assert response.status_code in [200, 429]
            if response.status_code == 200:
                data = response.json()
                assert "thought" in data
                assert "tool_called" in data
                assert "final_response" in data
