"""
Pytest suite for Payment API microservice.
"""
import pytest
from evals.generalization_repos.payment_api.app import process_payment


def test_process_payment_with_currency():
    res = process_payment({"amount": 100.0, "currency": "EUR"})
    assert res["status"] == "success"
    assert res["currency"] == "EUR"


def test_process_payment_missing_currency_defaults_to_usd():
    # Expect payment processing to succeed with default USD when currency key is omitted
    res = process_payment({"amount": 50.0})
    assert res["status"] == "success"
    assert res["currency"] == "USD"
