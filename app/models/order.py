import datetime
from sqlalchemy import Column, Integer, String, DateTime
from app.core.database import Base

class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    order_id = Column(String(50), unique=True, index=True, nullable=False)
    user_email = Column(String(100), index=True, nullable=False)
    amount_cents = Column(Integer, nullable=False)
    status = Column(String(20), default="pending", nullable=False)  # pending, paid, refunded
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    def __repr__(self):
        return f"<Order {self.order_id} - {self.status} - ${self.amount_cents/100}>"


class ProcessedWebhook(Base):
    """
    Idempotency Table:
    Guarantees that duplicate payment webhook retries produce the identical outcome 
    without double charging or duplicate order fulfillment.
    """
    __tablename__ = "processed_webhooks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(String(100), unique=True, index=True, nullable=False)
    event_type = Column(String(50), nullable=False)
    processed_at = Column(DateTime, default=datetime.datetime.utcnow)

    def __repr__(self):
        return f"<ProcessedWebhook {self.event_id} - {self.event_type}>"
