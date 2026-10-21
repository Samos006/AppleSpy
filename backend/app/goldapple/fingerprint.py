from __future__ import annotations

import sys

CHROME_VERSION = "131"

_UA_BY_PLATFORM = {
    "linux": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        f"(KHTML, like Gecko) Chrome/{CHROME_VERSION}.0.0.0 Safari/537.36",
        '"Linux"',
    ),
    "darwin": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        f"(KHTML, like Gecko) Chrome/{CHROME_VERSION}.0.0.0 Safari/537.36",
        '"macOS"',
    ),
    "win32": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        f"(KHTML, like Gecko) Chrome/{CHROME_VERSION}.0.0.0 Safari/537.36",
        '"Windows"',
    ),
}

def _current() -> tuple[str, str]:
    if sys.platform.startswith("linux"):
        return _UA_BY_PLATFORM["linux"]
    if sys.platform == "darwin":
        return _UA_BY_PLATFORM["darwin"]
    if sys.platform.startswith("win"):
        return _UA_BY_PLATFORM["win32"]
    return _UA_BY_PLATFORM["linux"]

USER_AGENT, CH_PLATFORM = _current()

SEC_CH_UA = (
    f'"Google Chrome";v="{CHROME_VERSION}", '
    f'"Chromium";v="{CHROME_VERSION}", '
    '"Not_A Brand";v="24"'
)
