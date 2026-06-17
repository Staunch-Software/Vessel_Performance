"""
EyegaugeAuthClient
==================
Lightweight wrapper for the /api/auth/login endpoint.

NOTE: When using the tb-rest-client SDK pipeline (EyegaugePipeline),
authentication is handled internally by EyegaugeTelemetryClient.login().
This class is kept for any standalone / legacy usage that still needs
a raw JWT token (e.g. debug_eyegauge.py).
"""

import requests
import logging

logger = logging.getLogger(__name__)


class EyegaugeAuthClient:
    def __init__(self, base_url: str, username: str, password: str):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.token: str | None = None

    def get_token(self) -> str:
        """Authenticates and retrieves the JWT token via raw HTTP POST."""
        logger.info("Authenticating with Eyegauge (Sea Vision) …")
        url = f"{self.base_url}/api/auth/login"
        payload = {"username": self.username, "password": self.password}

        try:
            response = requests.post(url, json=payload, timeout=30)
            response.raise_for_status()
            data = response.json()
            self.token = data.get("token") or data.get("accessToken")

            if not self.token:
                raise ValueError(
                    "Login successful but no token found in response."
                )

            logger.info("Eyegauge authentication successful.")
            return self.token

        except requests.exceptions.RequestException as e:
            logger.error(f"Eyegauge authentication failed: {e}")
            raise