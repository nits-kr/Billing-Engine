from pydantic_settings import BaseSettings
from pydantic import Field

class Settings(BaseSettings):
    PROJECT_NAME: str = "Enterprise Agentic Billing Engine"
    API_V1_STR: str = "/api/v1"
    
    # Database Settings (Async SQLite for dev, PostgreSQL in production)
    DATABASE_URL: str = Field(
        default="sqlite+aiosqlite:///./enterprise_app.db",
        description="Async Database URL"
    )
    
    # Redis Settings (Cache-Aside & Celery message broker)
    REDIS_URL: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection URL"
    )
    
    # Stripe / Payment Webhook Secret
    STRIPE_WEBHOOK_SECRET: str = "whsec_sample_secret_key_123"
    
    # Agentic AI Configuration (Groq Model with Function Calling)
    GROQ_API_KEY: str = Field(default="", description="Groq API key for Agentic AI")
    AI_MODEL: str = Field(default="openai/gpt-oss-120b", description="Fast inference LLM model")

    class Config:
        case_sensitive = True
        env_file = ".env"
        extra = "ignore"

# Global application settings instance
settings = Settings()
