"""
Pytest suite for Task Worker service.
"""
import os
import pytest
from evals.generalization_repos.task_worker.worker import get_redis_connection_config, execute_background_job


def test_get_redis_connection_config_fallback():
    # Clear REDIS_HOST from env if set
    os.environ.pop("REDIS_HOST", None)
    config = get_redis_connection_config()
    assert config["host"] == "localhost"
    assert config["status"] == "connected"


def test_execute_background_job():
    os.environ.pop("REDIS_HOST", None)
    res = execute_background_job("job_101")
    assert res["result"] == "completed"
