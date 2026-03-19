import os

# Risk-based gate timers
MEDIUM_RISK_TIMEOUT = int(os.getenv("SAFETY_MEDIUM_TIMEOUT_SECONDS", "60"))
HIGH_RISK_TIMEOUT = int(os.getenv("SAFETY_HIGH_TIMEOUT_SECONDS", "0"))  # 0 = wait forever
AUTO_APPROVE_LOW = os.getenv("SAFETY_AUTO_APPROVE_LOW", "true").lower() == "true"

# Retry
MAX_RETRIES = int(os.getenv("SAFETY_MAX_RETRIES", "2"))

# Health check thresholds
DISK_MIN_FREE_GB = float(os.getenv("SAFETY_DISK_MIN_FREE_GB", "2.0"))
LLM_HEALTH_TIMEOUT = int(os.getenv("SAFETY_LLM_HEALTH_TIMEOUT", "10"))
