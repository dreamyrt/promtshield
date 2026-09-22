import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "PromptShield — AI Firewall"
    VERSION: str = "1.0.0"
    ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "admin123")  # Пароль для перемикання захисту
    RISK_THRESHOLD: float = float(os.getenv("RISK_THRESHOLD", "0.6"))

settings = Settings()