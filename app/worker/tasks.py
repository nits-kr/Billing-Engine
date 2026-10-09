import time
import socket
import logging
from celery import Celery
from app.core.config import settings

logger = logging.getLogger(__name__)

from urllib.parse import urlparse

def is_broker_reachable(timeout: float = 0.1) -> bool:
    """Fast network health check before dispatching Celery tasks."""
    try:
        parsed = urlparse(settings.REDIS_URL)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 6379
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False

# 1. Celery Instance setup (Redis as Broker + Result Backend)
celery_app = Celery(
    "billing_worker",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL
)

# 2. Production Celery Configurations for Reliable Task Processing
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,             # Acknowledge tasks only after completion (Zero message loss)
    worker_prefetch_multiplier=1,    # Prevents worker task hoarding; enables fair distribution
    broker_connection_retry_on_startup=False,
    broker_connection_timeout=0.5,
    broker_connection_max_retries=1
)

# 3. Background Task 1: SendGrid Email Dispatch with Exponential Backoff
@celery_app.task(bind=True, max_retries=3, default_retry_delay=10)
def send_order_confirmation_email(self, user_email: str, order_id: str, amount_cents: int):
    """
    Simulates SendGrid Transactional Email dispatch in the background.
    Uses exponential backoff retries on transient network errors.
    """
    try:
        logger.info(f"[CELERY] Sending SendGrid email to {user_email} for Order {order_id}...")
        time.sleep(1)  # Simulates network I/O
        
        # Execute transactional email dispatch via SendGrid Client SDK
        logger.info(f"[CELERY SUCCESS] Email delivered to {user_email} (Amount: ${amount_cents/100})")
        return {"status": "sent", "email": user_email, "order_id": order_id}

    except Exception as exc:
        # Exponential backoff: 2^retries * 10 seconds (10s, 20s, 40s...)
        countdown = (2 ** self.request.retries) * 10
        logger.warning(f"[CELERY RETRY] Email failed. Retrying in {countdown}s. Error: {exc}")
        raise self.retry(exc=exc, countdown=countdown)

# 4. Background Task 2: Twilio SMS Alert
@celery_app.task
def send_sms_alert(phone_number: str, message: str):
    """Simulates Twilio SMS / WhatsApp notification."""
    logger.info(f"[CELERY] Dispatching Twilio SMS to {phone_number}: {message}")
    time.sleep(0.5)
    return {"status": "delivered", "to": phone_number}
