from slowapi import Limiter
from slowapi.util import get_remote_address

# Rate Limiter configured per IP address (defaults to in-memory fallback if Redis is down)
limiter = Limiter(key_func=get_remote_address, default_limits=["100/minute"])
