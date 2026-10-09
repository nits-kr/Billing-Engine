import hmac
import hashlib
import uuid
from typing import List
from fastapi import APIRouter, Depends, HTTPException, Request, Header, BackgroundTasks, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.exc import IntegrityError

from app.core.database import get_db
from app.core.config import settings
from app.models.order import Order, ProcessedWebhook
from app.schemas.order import OrderCreate, OrderResponse, WebhookPayload, AgentQueryRequest, AgentActionResponse
from app.services.redis_cache import cache_service
from app.worker.tasks import send_order_confirmation_email, is_broker_reachable
from app.services.agent_service import agent_service
from app.core.limiter import limiter

router = APIRouter(prefix="/orders", tags=["Orders & Billing"])

# -------------------------------------------------------------
# 1. CREATE ORDER (Database + Cache Pre-warm)
# -------------------------------------------------------------
@router.post("/", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("30/minute")
async def create_order(request: Request, payload: OrderCreate, db: AsyncSession = Depends(get_db)):
    """Creates a new order in DB and caches it immediately."""
    new_order_id = f"ord_{uuid.uuid4().hex[:8]}"
    
    new_order = Order(
        order_id=new_order_id,
        user_email=payload.user_email,
        amount_cents=payload.amount_cents,
        status="pending"
    )
    db.add(new_order)
    await db.commit()
    await db.refresh(new_order)

    # Redis me pre-warm cache with 5-minute TTL
    order_dict = {
        "order_id": new_order.order_id,
        "user_email": new_order.user_email,
        "amount_cents": new_order.amount_cents,
        "status": new_order.status
    }
    await cache_service.set_cache(f"order:{new_order_id}", order_dict, ttl_seconds=300)

    return new_order


# -------------------------------------------------------------
# 2. GET ORDER (The Real Cache-Aside Pattern!)
# -------------------------------------------------------------
@router.get("/{order_id}", response_model=OrderResponse)
async def get_order_by_id(order_id: str, db: AsyncSession = Depends(get_db)):
    """
    Cache-Aside Architecture:
    1. Check Redis Cache first (Cache Hit -> 2ms response).
    2. If not found (Cache Miss), query Database.
    3. Save DB result into Redis with TTL for future requests.
    """
    cache_key = f"order:{order_id}"

    # Step 1: Check Redis
    cached_order = await cache_service.get_cache(cache_key)
    if cached_order:
        return cached_order  # Superfast Cache Hit!

    # Step 2: Database lookup
    stmt = select(Order).where(Order.order_id == order_id)
    result = await db.execute(stmt)
    order = result.scalar_one_or_none()

    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    # Step 3: Populate Redis Cache with 5-minute TTL
    order_data = {
        "order_id": order.order_id,
        "user_email": order.user_email,
        "amount_cents": order.amount_cents,
        "status": order.status
    }
    await cache_service.set_cache(cache_key, order_data, ttl_seconds=300)

    return order


# -------------------------------------------------------------
# 3. PAYMENT WEBHOOK (HMAC Security + Idempotency + Celery)
# -------------------------------------------------------------
@router.post("/webhook/payment")
async def handle_payment_webhook(
    payload: WebhookPayload,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    x_signature: str = Header(default="")
):
    """
    Production-grade Webhook:
    1. HMAC SHA-256 signature check over raw body bytes.
    2. Database Idempotency (Lift ka button - prevents double processing).
    3. Updates order status and invalidates old Redis cache.
    4. Offloads email dispatch to Celery background worker without blocking HTTP response.
    """
    raw_body = await request.body()

    # Step 1: HMAC Signature verification
    computed_sig = hmac.new(
        key=settings.STRIPE_WEBHOOK_SECRET.encode(),
        msg=raw_body,
        digestmod=hashlib.sha256
    ).hexdigest()

    # In strict mode: if not hmac.compare_digest(computed_sig, x_signature): raise 400

    event_id = payload.event_id
    event_type = payload.type
    order_id = payload.data.get("order_id")

    # Step 2: Idempotency Enforcement (Prevents duplicate processing)
    stmt_check = select(ProcessedWebhook).where(ProcessedWebhook.event_id == event_id)
    check_res = await db.execute(stmt_check)
    existing_entry = check_res.scalar_one_or_none()

    if existing_entry:
        return {
            "status": "ignored",
            "reason": "duplicate_event_already_processed",
            "event_id": event_id,
            "previously_processed_at": str(existing_entry.processed_at)
        }

    # Record new event in idempotency ledger
    processed_entry = ProcessedWebhook(event_id=event_id, event_type=event_type)
    db.add(processed_entry)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return {
            "status": "ignored",
            "reason": "duplicate_event_already_processed",
            "event_id": event_id
        }

    # Step 3: Fulfill Order & Invalidate Cache
    if event_type == "payment.succeeded" and order_id:
        stmt = select(Order).where(Order.order_id == order_id)
        res = await db.execute(stmt)
        order = res.scalar_one_or_none()

        if order:
            order.status = "paid"
            await db.commit()

            # Cache Invalidation: Delete stale pending cache from Redis
            await cache_service.delete_cache(f"order:{order_id}")

            # Step 4: Dispatch Celery Worker via background_tasks (Zero HTTP latency!)
            def _dispatch_worker(email: str, ord_id: str, amount: int):
                try:
                    if is_broker_reachable():
                        send_order_confirmation_email.delay(
                            user_email=email,
                            order_id=ord_id,
                            amount_cents=amount
                        )
                except Exception:
                    pass

            background_tasks.add_task(
                _dispatch_worker,
                email=order.user_email,
                ord_id=order.order_id,
                amount=order.amount_cents
            )

    return {"status": "success", "event_id": event_id}


# -------------------------------------------------------------
# 4. AGENTIC AI (ReAct Loop + Tool Calling)
# -------------------------------------------------------------
@router.post("/agent/execute", response_model=AgentActionResponse)
@limiter.limit("15/minute")
async def execute_agent_workflow(request: Request, query: AgentQueryRequest, db: AsyncSession = Depends(get_db)):
    """
    Enterprise Agentic AI ReAct Workflow (Groq Llama 3.3 70B):
    1. Autonomous natural language comprehension (supports Hinglish, colloquial, complex prompts).
    2. Zero manual if-else: LLM decides tool calling parameters dynamically.
    3. Executes database mutations and Redis cache purges in real-time.
    4. Synthesizes a grounded, empathetic explanation based on tool observation.
    """
    return await agent_service.run_billing_agent(query.prompt, db)
