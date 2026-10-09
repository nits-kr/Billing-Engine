import datetime
from typing import Dict, Any, Optional
from pydantic import BaseModel, EmailStr, Field, ConfigDict

# 1. OrderCreate: Inbound request schema for order creation
class OrderCreate(BaseModel):
    user_email: EmailStr = Field(..., examples=["customer@example.com"])
    amount_cents: int = Field(..., gt=0, examples=[4999], description="Amount in cents ($49.99 = 4999)")

# 2. OrderResponse: Serialized API response contract
class OrderResponse(BaseModel):
    order_id: str
    user_email: EmailStr
    amount_cents: int
    status: str
    created_at: Optional[datetime.datetime] = None

    # Enable automatic serialization from SQLAlchemy ORM models (Pydantic V2)
    model_config = ConfigDict(from_attributes=True)

# 3. WebhookPayload: Inbound payment gateway webhook contract
class WebhookPayload(BaseModel):
    event_id: Optional[str] = Field(
        default=None,
        description="Unique Stripe Event ID (e.g. evt_xxx). Leave blank or omit to auto-generate a fresh unique ID."
    )
    type: str = Field(default="payment.succeeded", description="Event type emitted by payment provider")
    data: Dict[str, Any] = Field(
        description="Payload data containing order_id (e.g. {'order_id': 'ord_12345678'})"
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "type": "payment.succeeded",
                "data": {
                    "order_id": "ord_paste_your_order_id_here"
                }
            }
        }
    }

# 4. Agentic AI Schemas: Natural Language Prompt aur Tool-calling result
class AgentQueryRequest(BaseModel):
    prompt: str = Field(..., examples=["Check order ord_101 and refund it"])

class AgentActionResponse(BaseModel):
    thought: str
    tool_called: str
    tool_result: Dict[str, Any]
    final_response: str
