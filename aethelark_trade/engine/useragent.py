"""The User-Agent this module presents to SEC.

SEC's access policy requires a declared, contactable User-Agent on every
request, and treats a browser-impersonating string as a violation rather than a
clever workaround. So a contact has to be in there.

The question is *whose*. A single hardcoded address is correct for one operator
running one machine and wrong the moment the module is installed by somebody
else: every user's traffic then identifies as that one person, and a stranger
exhausting the 10 req/s budget gets that person's contact on SEC's record.

So the default identifies the *software* and points at the project, which is a
contactable channel and standard practice for a bot. An operator running this
at volume should set their own:

    export ATRADE_SEC_CONTACT="you@example.com"

Read at call time, not import time, so setting it in a running process works.
"""

from __future__ import annotations

import os

PROJECT_URL = "https://github.com/ciopialex/Aethelark-Trade"
PRODUCT = "Aethelark-Trade"
VERSION = "1.0"

#: Set this and every SEC request carries it instead of the project URL.
CONTACT_ENV = "ATRADE_SEC_CONTACT"


def sec_contact() -> str:
    """The contact SEC should reach, from the environment or the project URL."""
    return (os.environ.get(CONTACT_ENV) or "").strip() or f"+{PROJECT_URL}"


def sec_user_agent(purpose: str | None = None) -> str:
    """A declared, contactable User-Agent in SEC's expected shape.

    >>> sec_user_agent()                       # doctest: +ELLIPSIS
    'Aethelark-Trade/1.0 (+https://github.com/...)'
    """
    product = f"{PRODUCT}/{VERSION}"
    if purpose:
        product = f"{product} {purpose}"
    return f"{product} ({sec_contact()})"
