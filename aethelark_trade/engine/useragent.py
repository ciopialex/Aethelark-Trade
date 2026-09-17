"""The User-Agent this module presents to SEC.

SEC's access policy requires a declared, contactable User-Agent on every
request, and treats a browser-impersonating string as a violation rather than a
clever workaround. So a contact has to be in there, and it has to be one they
accept.

**Measured against data.sec.gov on 2026-09-17** — this is not guesswork, and it
rules out the obvious "just point at the project" answer:

    "Aethelark-Trade/1.0 (contact@example.com)"                  -> HTTP 200
    "someone@example.com"                                        -> HTTP 200
    "Aethelark-Trade/1.0 (+https://github.com/owner/repo)"       -> HTTP 403
    "Aethelark-Trade/1.0 (+https://…; noreply@github.com)"       -> HTTP 403

SEC wants an email address and rejects a URL. A repository link is therefore
not a usable default.

That leaves two options for a module other people install: ship the author's
address, or ask the operator for theirs. Shipping the author's is what the
private version did, and it is wrong once distributed — every installation's
traffic then identifies as one person, and a stranger exhausting the 10 req/s
budget puts that person's name on SEC's record of it.

So this module asks. One command:

    atrade register --contact you@example.com     # stored, persists
    export ATRADE_SEC_CONTACT="you@example.com"   # or per-shell

Resolution order: environment, then ~/.aethelark/config.toml. Read at call
time so a value set in a running process takes effect, and so importing a
module never raises — the failure belongs at the request, where the message
can say what to do.
"""

from __future__ import annotations

import os
from pathlib import Path

PRODUCT = "Aethelark-Trade"
VERSION = "1.0"

#: Environment variable that wins over stored config.
CONTACT_ENV = "ATRADE_SEC_CONTACT"

#: Where `atrade register --contact` persists it.
CONFIG_PATH = Path.home() / ".aethelark" / "config.toml"

#: RFC 2606 reserved TLD. Used only so that importing a module without a
#: configured contact does not raise; any SEC request carrying it is refused
#: locally by `require_sec_contact()` before it reaches the network.
PLACEHOLDER = "unconfigured@aethelark-trade.invalid"


class SECContactRequired(RuntimeError):
    """Raised instead of sending SEC a request they will answer with 403."""

    def __init__(self) -> None:
        super().__init__(
            "SEC requires a contactable email in the User-Agent, and refuses "
            "requests without one (HTTP 403).\n\n"
            "Set yours once:\n"
            "    atrade register --contact you@example.com\n"
            "or for this shell only:\n"
            f"    export {CONTACT_ENV}='you@example.com'\n\n"
            "It identifies who is making the requests. Using somebody else's "
            "means their name is on your traffic."
        )


def _from_config() -> str | None:
    try:
        import tomllib

        data = tomllib.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    value = (data.get("sec", {}) or {}).get("contact")
    return str(value).strip() if value else None


def looks_like_email(value: str) -> bool:
    """Good enough to catch a URL or an empty string, which is the failure
    mode that matters. Not an RFC 5322 validator."""
    value = (value or "").strip()
    if "://" in value or " " in value:
        return False
    local, _, domain = value.partition("@")
    return bool(local) and "." in domain


def sec_contact() -> str | None:
    """The configured contact, or None. Environment wins over stored config."""
    for candidate in (os.environ.get(CONTACT_ENV), _from_config()):
        candidate = (candidate or "").strip()
        if candidate and looks_like_email(candidate):
            return candidate
    return None


def store_contact(contact: str) -> Path:
    """Persist a contact to ~/.aethelark/config.toml. Returns the path."""
    contact = (contact or "").strip()
    if not looks_like_email(contact):
        raise ValueError(
            f"{contact!r} is not an email address. SEC needs one they can "
            f"reach; a URL is refused with HTTP 403.")

    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    existing = ""
    if CONFIG_PATH.exists():
        existing = CONFIG_PATH.read_text(encoding="utf-8")
        # Drop any previous [sec] block rather than appending a second one.
        kept, skipping = [], False
        for line in existing.splitlines():
            stripped = line.strip()
            if stripped.startswith("["):
                skipping = stripped == "[sec]"
            if not skipping:
                kept.append(line)
        existing = "\n".join(kept).rstrip()

    body = (existing + "\n\n" if existing else "")
    body += (
        "[sec]\n"
        "# Sent to SEC in the User-Agent on every request. They require a\n"
        "# contactable address and refuse requests without one.\n"
        f'contact = "{contact}"\n'
    )
    CONFIG_PATH.write_text(body, encoding="utf-8")
    return CONFIG_PATH


def sec_user_agent(purpose: str | None = None) -> str:
    """A declared, contactable User-Agent in the shape SEC accepts.

    Never raises: module-level constants are built from this at import time.
    Without a configured contact it carries `PLACEHOLDER`, and
    `require_sec_contact()` stops the request before it is sent.
    """
    product = f"{PRODUCT}/{VERSION}"
    if purpose:
        product = f"{product} {purpose}"
    return f"{product} ({sec_contact() or PLACEHOLDER})"


def require_sec_contact() -> str:
    """The contact, or raise with instructions. Call before hitting SEC."""
    contact = sec_contact()
    if contact is None:
        raise SECContactRequired()
    return contact
