from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from app.core.config import settings
from app.core.database import engine, Base
from app.api.v1.router import api_router

# 1. Lifespan Context Manager: Application lifecycle management
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Ensure database tables are created
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print(f">> [STARTUP] {settings.PROJECT_NAME} is live! Database tables verified.")
    yield
    # Shutdown: Cleanly dispose of connection pools
    await engine.dispose()
    print(">> [SHUTDOWN] Database connections cleanly disposed.")

# 2. FastAPI Application Initialization
app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Production-grade Agentic AI & Billing Microservice with Redis Cache and Celery Workers",
    version="1.0.0",
    lifespan=lifespan
)

# 3. CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 4. Include Master API Router (/api/v1)
app.include_router(api_router, prefix=settings.API_V1_STR)

# 5. Root Healthcheck Endpoint
@app.get("/", tags=["Health"])
async def root():
    return {
        "status": "healthy",
        "service": settings.PROJECT_NAME,
        "docs_url": "/docs",
        "endpoints": {
            "orders": f"{settings.API_V1_STR}/orders",
            "webhook": f"{settings.API_V1_STR}/orders/webhook/payment",
            "agent": f"{settings.API_V1_STR}/orders/agent/execute"
        }
    }

if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
