import json
import logging
from typing import Dict, Any, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from groq import AsyncGroq
from app.core.config import settings
from app.models.order import Order
from app.services.redis_cache import cache_service
from app.schemas.order import AgentActionResponse

logger = logging.getLogger(__name__)

# -------------------------------------------------------------
# 1. TOOL SCHEMAS FOR GROQ LLM (Function Calling Definition)
# -------------------------------------------------------------
AGENT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "query_order_status",
            "description": "Fetch real-time order details from the database including status, amount, and user email.",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {
                        "type": "string",
                        "description": "The unique identifier of the order (e.g., ord_101, ord_a735b8a6)"
                    }
                },
                "required": ["order_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "process_order_refund",
            "description": "Processes an official refund for an order in the database, updates status to 'refunded', and invalidates cache.",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {
                        "type": "string",
                        "description": "The unique order ID to refund"
                    },
                    "reason": {
                        "type": "string",
                        "description": "The reason for refund requested by the customer (e.g. damaged parcel, wrong item, cancellation)"
                    }
                },
                "required": ["order_id", "reason"]
            }
        }
    }
]

SYSTEM_PROMPT = """You are an Enterprise AI Billing and Customer Operations Assistant.
You have direct tool access to live customer orders in the database.
- If a customer asks to check an order status, inspect it, or track it, call `query_order_status`.
- If a customer asks for a refund, return, or money back, call `process_order_refund`.
- Extract order IDs precisely (e.g., tokens starting with 'ord_').
- If the customer does not provide an order ID, ask them politely for the order ID.
- Always be professional, empathetic, and clear. Ground your final answers strictly in the tool observations.
"""

# -------------------------------------------------------------
# 2. BACKEND PYTHON TOOLS (Execute against Database & Redis)
# -------------------------------------------------------------
async def execute_query_order_status(db: AsyncSession, order_id: str) -> Dict[str, Any]:
    """Tool: Database & Cache query for order status."""
    # 1. Check Redis cache first
    cached = await cache_service.get_cache(f"order:{order_id}")
    if cached:
        return {
            "source": "cache",
            "order_id": order_id,
            "user_email": cached.get("user_email"),
            "amount_cents": cached.get("amount_cents"),
            "status": cached.get("status"),
            "created_at": cached.get("created_at")
        }

    # 2. Query DB
    stmt = select(Order).where(Order.order_id == order_id)
    res = await db.execute(stmt)
    order = res.scalar_one_or_none()

    if not order:
        return {"error": "Order not found in database", "order_id": order_id}

    return {
        "source": "database",
        "order_id": order.order_id,
        "user_email": order.user_email,
        "amount_cents": order.amount_cents,
        "status": order.status,
        "created_at": str(order.created_at)
    }

async def execute_process_order_refund(db: AsyncSession, order_id: str, reason: str) -> Dict[str, Any]:
    """Tool: Mutates database to refund order and purges Redis cache."""
    stmt = select(Order).where(Order.order_id == order_id)
    res = await db.execute(stmt)
    order = res.scalar_one_or_none()

    if not order:
        return {"error": "Order not found in records", "order_id": order_id}

    if order.status == "refunded":
        return {
            "status": "already_refunded",
            "order_id": order_id,
            "message": "Order was already refunded previously."
        }

    if order.status == "pending":
        # Cannot refund an unpaid order; mark as cancelled instead
        order.status = "cancelled"
        await db.commit()
        await db.refresh(order)
        await cache_service.delete_cache(f"order:{order_id}")
        return {
            "success": True,
            "order_id": order_id,
            "amount_cents": order.amount_cents,
            "status": "cancelled",
            "message": "Order was pending payment and had not been charged. The order has been cancelled instead of refunded.",
            "reason_recorded": reason
        }

    # Update status to refunded (ACID transaction)
    order.status = "refunded"
    await db.commit()
    await db.refresh(order)

    # Invalidate Redis cache
    await cache_service.delete_cache(f"order:{order_id}")

    return {
        "success": True,
        "order_id": order_id,
        "amount_cents": order.amount_cents,
        "refund_amount_dollars": round(order.amount_cents / 100, 2),
        "status": "refunded",
        "reason_recorded": reason
    }


# -------------------------------------------------------------
# 3. ENTERPRISE REACT AGENT LOOP (Groq LLM + Function Calling)
# -------------------------------------------------------------
class AgentService:
    def __init__(self):
        self.client = None
        if settings.GROQ_API_KEY and not settings.GROQ_API_KEY.startswith("gsk_your"):
            self.client = AsyncGroq(api_key=settings.GROQ_API_KEY)

    async def run_billing_agent(self, user_prompt: str, db: AsyncSession) -> AgentActionResponse:
        """
        Executes an autonomous ReAct loop:
        1. Sends prompt + Tool definitions to LLM.
        2. Detects if tool_calls were emitted.
        3. Executes the backend Python function.
        4. Re-feeds observation to LLM for final grounded synthesis.
        """
        if not self.client:
            # Fallback if API key is not configured
            return await self._fallback_deterministic_agent(user_prompt, db)

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ]

        try:
            # Step 1: Initial LLM Inference (Reasoning + Tool Decision)
            response = await self.client.chat.completions.create(
                model=settings.AI_MODEL,
                messages=messages,
                tools=AGENT_TOOLS,
                tool_choice="auto",
                temperature=0.2,
                max_tokens=500
            )

            choice = response.choices[0].message

            # Case A: LLM decided to call a backend tool (Function Calling)
            if choice.tool_calls:
                tool_call = choice.tool_calls[0]
                function_name = tool_call.function.name
                args = json.loads(tool_call.function.arguments)

                logger.info(f"[AGENT TOOL CALLED] {function_name} with args: {args}")

                # Step 2: Tool Execution (Acting)
                if function_name == "query_order_status":
                    tool_result = await execute_query_order_status(db, args.get("order_id", ""))
                elif function_name == "process_order_refund":
                    tool_result = await execute_process_order_refund(
                        db,
                        order_id=args.get("order_id", ""),
                        reason=args.get("reason", "Customer requested refund")
                    )
                else:
                    tool_result = {"error": f"Unknown tool: {function_name}"}

                # Step 3: Send Observation back to LLM for Final Answer Synthesis
                messages.append(choice)  # Assistant's tool_calls message
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": function_name,
                    "content": json.dumps(tool_result)
                })

                second_response = await self.client.chat.completions.create(
                    model=settings.AI_MODEL,
                    messages=messages,
                    temperature=0.3,
                    max_tokens=300
                )

                final_answer = second_response.choices[0].message.content

                thought_summary = f"LLM analyzed prompt, identified intent '{function_name}', and dispatched tool with params: {args}."

                return AgentActionResponse(
                    thought=thought_summary,
                    tool_called=function_name,
                    tool_result=tool_result,
                    final_response=final_answer
                )

            # Case B: General conversational question (No tool needed)
            else:
                return AgentActionResponse(
                    thought="No action tool required. Answered via conversational intelligence.",
                    tool_called="none",
                    tool_result={},
                    final_response=choice.content or "Hello! I am your AI Billing Assistant. How can I help you today?"
                )

        except Exception as e:
            logger.error(f"[AGENT LLM ERROR] Falling back to deterministic agent: {e}")
            return await self._fallback_deterministic_agent(user_prompt, db)

    async def _fallback_deterministic_agent(self, prompt: str, db: AsyncSession) -> AgentActionResponse:
        """Deterministic fallback if external LLM network is down."""
        text = prompt.lower()
        words = text.split()
        target_id = next((w.strip(".,!?:;'\"()") for w in words if w.strip(".,!?:;'\"()").startswith("ord_")), "ord_sample")

        if "refund" in text or "reverse" in text or "cancel" in text:
            result = await execute_process_order_refund(db, target_id, reason="Customer fallback request")
            return AgentActionResponse(
                thought=f"[Fallback Engine] Detected refund intent for {target_id}.",
                tool_called="process_order_refund",
                tool_result=result,
                final_response=f"Refund request for {target_id} processed. Current status: {result.get('status')}."
            )
        else:
            result = await execute_query_order_status(db, target_id)
            return AgentActionResponse(
                thought=f"[Fallback Engine] Querying status for {target_id}.",
                tool_called="query_order_status",
                tool_result=result,
                final_response=f"Order {target_id} details retrieved: Status is '{result.get('status')}'."
            )

agent_service = AgentService()
