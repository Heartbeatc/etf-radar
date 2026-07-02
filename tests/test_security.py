from __future__ import annotations

import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.security import install_security_middleware


def _client(**overrides) -> TestClient:
    values = {
        "security_allowed_hosts": "testserver",
        "security_login_rate_limit_per_minute": 2,
        "security_api_rate_limit_per_minute": 10,
        "security_rate_limit_window_seconds": 60,
        "security_max_body_bytes": 1024,
    }
    values.update(overrides)
    settings = Settings(**values)
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    install_security_middleware(app, settings)

    @app.get("/health")
    async def health() -> dict[str, bool]:
        return {"ok": True}

    @app.post("/api/v1/auth/login")
    async def login() -> dict[str, bool]:
        return {"ok": False}

    return TestClient(app)


class SecurityMiddlewareTest(unittest.TestCase):
    def test_security_headers_are_added(self) -> None:
        response = _client().get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["x-frame-options"], "DENY")
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")
        self.assertIn("frame-ancestors 'none'", response.headers["content-security-policy"])

    def test_trusted_host_rejects_unexpected_hosts(self) -> None:
        response = _client().get("/health", headers={"host": "attacker.example"})

        self.assertEqual(response.status_code, 400)

    def test_request_size_limit_rejects_large_bodies(self) -> None:
        response = _client().post("/api/v1/auth/login", content=b"x" * 2048)

        self.assertEqual(response.status_code, 413)

    def test_login_rate_limit_rejects_bursts(self) -> None:
        client = _client()

        self.assertEqual(client.post("/api/v1/auth/login", json={}).status_code, 200)
        self.assertEqual(client.post("/api/v1/auth/login", json={}).status_code, 200)
        response = client.post("/api/v1/auth/login", json={})

        self.assertEqual(response.status_code, 429)
        self.assertIn("retry-after", response.headers)


if __name__ == "__main__":
    unittest.main()
