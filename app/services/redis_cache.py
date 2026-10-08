import json
import logging
from typing import Optional, Any
import redis.asyncio as aioredis
from app.core.config import settings

logger = logging.getLogger(__name__)

class RedisCacheService:
    def __init__(self):
        # Redis Connection Client (Async)
        self.redis_client = aioredis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=0.2,
            socket_timeout=0.2
        )

    async def get_cache(self, key: str) -> Optional[Any]:
        """Retrieves cached entity from Redis with graceful database fallback."""
        try:
            cached_data = await self.redis_client.get(key)
            if cached_data:
                logger.info(f"[REDIS CACHE HIT] Key: {key}")
                return json.loads(cached_data)
            logger.info(f"[REDIS CACHE MISS] Key: {key}")
            return None
        except Exception as e:
            logger.warning(f"Redis connection unavailable, falling back to database: {e}")
            return None

    async def set_cache(self, key: str, value: Any, ttl_seconds: int = 300) -> bool:
        """Stores serialized JSON entity in Redis with TTL expiration."""
        try:
            serialized_value = json.dumps(value)
            await self.redis_client.set(key, serialized_value, ex=ttl_seconds)
            return True
        except Exception as e:
            logger.warning(f"Failed to set Redis cache key '{key}': {e}")
            return False

    async def delete_cache(self, key: str) -> bool:
        """Purges stale cache key upon database mutation (Cache Invalidation)."""
        try:
            await self.redis_client.delete(key)
            logger.info(f"[REDIS CACHE INVALIDATED] Key: {key}")
            return True
        except Exception as e:
            logger.warning(f"Failed to invalidate Redis cache key '{key}': {e}")
            return False

# Global cache service instance
cache_service = RedisCacheService()
