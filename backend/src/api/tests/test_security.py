"""
backend/src/api/tests/test_security.py
=======================================
Integration test suite for JWT authentication and Rate Limiting.
Uses FastAPI's TestClient to verify endpoints behavior.
"""
import os
import sys
from fastapi.testclient import TestClient

# Set project root
_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
sys.path.insert(0, _PROJECT_ROOT)

from backend.src.api.main import app


def test_security_pipeline():
    print("\n" + "=" * 60)
    print("TEST: SECURITY PIPELINE (JWT AUTH & RATE LIMITING)")
    print("=" * 60)

    client = TestClient(app)

    # 1. Verify Public Endpoints
    print("[1] Verifying public endpoints...")
    resp_health = client.get("/health")
    assert resp_health.status_code == 200, f"Health check failed: {resp_health.status_code}"
    
    resp_status = client.get("/agent/status")
    assert resp_status.status_code == 200, f"Agent status endpoint failed: {resp_status.status_code}"
    print("    - GET /health and GET /agent/status are public.")

    # 2. Verify Securing routes (should block without token)
    print("[2] Verifying authentication gate on secured routes...")
    resp_chat = client.post("/agent/chat", json={"query": "VJ100"})
    # Since ENV is default development, no-credentials might fallback or throw 401 based on env configuration.
    # In auth.py we wrote: if credentials not provided, and not IS_PROD, we allow anonymized dev access.
    # Let's set ENV=production in the environment to strictly test the JWT gating!
    os.environ["ENV"] = "production"
    
    resp_chat_prod = client.post("/agent/chat", json={"query": "VJ100"})
    assert resp_chat_prod.status_code == 401, f"Should block without token in prod. Got: {resp_chat_prod.status_code}"
    print("    - Blocked unauthorized POST /agent/chat (401 Unauthorized)")

    # 3. Generate JWT Token
    print("[3] Testing token generation endpoint...")
    resp_token = client.post("/agent/token")
    assert resp_token.status_code == 200, f"Failed to generate token: {resp_token.status_code}"
    token_data = resp_token.json()
    assert "access_token" in token_data
    token = token_data["access_token"]
    print("    - Successfully generated JWT token.")

    # 4. Verify Access with JWT Token
    print("[4] Testing access using generated JWT Token...")
    headers = {"Authorization": f"Bearer {token}"}
    # We will trigger the route. Note: it might try to connect to vLLM and fallback or succeed.
    # Let's see if we get a response (200 or 500, but not 401)
    resp_chat_auth = client.post("/agent/chat", json={"query": "VJ100"}, headers=headers)
    assert resp_chat_auth.status_code in [200, 500], f"Auth token failed: {resp_chat_auth.status_code} - {resp_chat_auth.text}"
    print("    - JWT token authorization validated successfully (No 401).")

    # 5. Verify Access with Dev Bypass Token
    print("[5] Testing access using Dev Bypass Token...")
    headers_bypass = {"Authorization": "Bearer vj-revenue-dev-token"}
    resp_chat_bypass = client.post("/agent/chat", json={"query": "VJ100"}, headers=headers_bypass)
    assert resp_chat_bypass.status_code in [200, 500], f"Bypass token failed: {resp_chat_bypass.status_code}"
    print("    - Dev Bypass token validated successfully.")

    # 6. Verify Rate Limiter (Max 10 calls per minute)
    print("[6] Testing Rate Limiter (Max 10 calls / min)...")
    # Reset limit history for tests by clearing or just calling until blocked
    blocked = False
    for i in range(12):
        resp = client.post("/agent/chat", json={"query": "VJ100"}, headers=headers_bypass)
        if resp.status_code == 429:
            blocked = True
            print(f"    - Blocked at request {i+1} with 429 Too Many Requests (Correct behaviour).")
            break
    
    assert blocked, "Rate limiter did not block after 10 requests!"
    print("\n[SUCCESS] Security verification suite passed successfully!")


if __name__ == "__main__":
    test_security_pipeline()
