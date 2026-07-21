"""
Payment API Microservice (Flask).
"""
from flask import Flask, jsonify, request

app = Flask(__name__)


def process_payment(data: dict) -> dict:
    """Process payment payload."""
    if not isinstance(data, dict):
        raise ValueError("Invalid payload format")

    amount = data["amount"]
    # Buggy code: direct dict access without fallback
    currency = data["currency"]

    return {
        "status": "success",
        "amount": amount,
        "currency": currency,
        "transaction_id": "tx_998877",
    }


@app.route("/pay", methods=["POST"])
def pay_endpoint():
    try:
        req_data = request.get_json() or {}
        res = process_payment(req_data)
        return jsonify(res), 200
    except KeyError as e:
        return jsonify({"error": f"Missing required field: {e}"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500
