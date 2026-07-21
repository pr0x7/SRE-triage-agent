"""
Task Worker Service (Background processing).
"""
import os


def get_redis_connection_config() -> dict:
    """Get Redis host and port config."""
    # Buggy code: direct dict access without fallback for missing environment variable
    host = os.environ["REDIS_HOST"]
    port = int(os.environ.get("REDIS_PORT", 6379))
    return {"host": host, "port": port, "status": "connected"}


def execute_background_job(job_id: str) -> dict:
    config = get_redis_connection_config()
    return {"job_id": job_id, "host": config["host"], "result": "completed"}
