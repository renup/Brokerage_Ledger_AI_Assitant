import hashlib
import hmac
import time

import httpx
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from assistant.config import settings

# Reads the "Authorization: Bearer <token>" header (None if missing)
bearer_scheme = HTTPBearer(auto_error=False)

# How long we remember who a token belongs to
CACHE_SECONDS = 60
# token -> (time it expires, the user info). Lives in memory; resets when the server restarts.
_cache: dict[str, tuple[float, dict]] = {}

# Turns a customer id into a scrambled, one-way value. We store this in the database
# instead of the real id, so a leaked assistant.db doesn't list customer ids.
# hmac mixes in a secret. A plain hash of "1", "2", "3"... could be reversed by trying
# every small number; with a secret, an attacker can't.
def customer_hash(customer_id: int) -> str:
    return hmac.new(
        settings.customer_hash_secret.encode(), str(customer_id).encode(), hashlib.sha3_256
        # hexdigest() turns the result into readable text. The () is needed to call it.
    ).hexdigest()

# Pulls the raw token out of the "Authorization: Bearer <token>" header.
# A separate dependency because two things need the token: get_current_user (to ask who it
# belongs to) and the LedgerClient (to make calls as that person).
def get_bearer_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> str:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Missing token")
    return credentials.credentials

# A dependency, like get_current_customer in ledger-core. But this service has no
# customer database. It asks ledger-core instead: "who owns this token?"
# "async def" because it waits for another service's answer.
async def get_current_user(token: str = Depends(get_bearer_token)) -> dict:
    # Seen this token in the last 60 seconds? Reuse the answer, skip the network call.
    # time.monotonic() is a clock that only counts forward, so it's safe for timers.
    cached = _cache.get(token)
    if cached is not None and cached[0] > time.monotonic():
        return cached[1]

    try:
        # httpx makes web requests from code (like Postman). "async with" opens the
        # connection and closes it afterwards. timeout=5: give up after 5 seconds.
        async with httpx.AsyncClient(timeout=5) as client:
            # "await" pauses here until ledger-core answers; other requests can run meanwhile
            response = await client.get(
                f"{settings.ledger_core_url}/me",
                # Pass the caller's own token along
                headers={"Authorization": f"Bearer {token}"},
            )
    except httpx.RequestError:
        # We couldn't reach ledger-core at all. 503 = "a service we depend on is down".
        raise HTTPException(status_code=503, detail="Login service unavailable")

    # Anything but 200 (usually 401) means ledger-core rejected the token
    if response.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user = response.json()  # {"id": 1, "name": "Maya Patel", "email": "..."}
    now = time.monotonic()
    # Housekeeping: delete expired entries so the cache can't grow forever
    for key in [k for k, (expires, _) in _cache.items() if expires <= now]:
        del _cache[key]
    # Remember this answer for 60 seconds, then hand it back
    _cache[token] = (now + CACHE_SECONDS, user)
    return user

