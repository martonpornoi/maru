from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_production_settings_disable_dev_login_and_enable_security_defaults() -> None:
    env = os.environ.copy()
    env.update(
        {
            "MARU_DEBUG": "0",
            "MARU_DEV_LOGIN_ENABLED": "1",
            "PYTHONPATH": str(PROJECT_ROOT / "src"),
        }
    )

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "\n".join(
                [
                    "from maru import settings",
                    "print(settings.DEBUG)",
                    "print(settings.MARU_DEV_LOGIN_ENABLED)",
                    "print(settings.SECURE_SSL_REDIRECT)",
                    "print(settings.SESSION_COOKIE_SECURE)",
                    "print(settings.CSRF_COOKIE_SECURE)",
                    "print(settings.SECURE_HSTS_SECONDS)",
                    "print(settings.SECURE_CONTENT_TYPE_NOSNIFF)",
                    "print(settings.X_FRAME_OPTIONS)",
                ]
            ),
        ],
        check=True,
        capture_output=True,
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
    )

    assert result.stdout.splitlines() == [
        "False",
        "False",
        "True",
        "True",
        "True",
        "31536000",
        "True",
        "DENY",
    ]
