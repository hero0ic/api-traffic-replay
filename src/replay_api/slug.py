"""Turn a project name into a URL-safe unique slug."""

import re
import secrets


def slugify(name: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    if not cleaned:
        cleaned = "project"
    return f"{cleaned}-{secrets.token_hex(3)}"
