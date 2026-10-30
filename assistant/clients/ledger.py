import httpx


# We couldn't reach ledger-core at all (it's down, or too slow)
class LedgerUnavailableError(Exception):
    pass


# ledger-core answered, but said no (404 not found, 401 bad token, ...)
class LedgerRejectedError(Exception):
    def __init__(self, status_code: int):
        super().__init__(f"ledger-core answered {status_code}")
        # Kept so the caller can tell a 404 ("not yours or doesn't exist") from other failures
        self.status_code = status_code


# The only code in the assistant that talks to ledger-core's customer endpoints.
# One instance per request: it holds THIS customer's token, so every call is made as them.
class LedgerClient:
    # "http" is a shared connection pool created once at startup, with ledger-core's address
    # already set as its base_url (we wire that in the next step). "token" is the caller's own.
    def __init__(self, http: httpx.AsyncClient, token: str):
        self.http = http
        self.headers = {"Authorization": f"Bearer {token}"}

    # The one place a request is made, so timeouts and error handling exist exactly once
    async def _get(self, path: str, params: dict | None = None):
        try:
            # timeout=2.0: give up after 2 seconds instead of making the customer wait
            response = await self.http.get(path, headers=self.headers, params=params, timeout=2.0)
        except httpx.RequestError as exc:
            # "from exc" keeps the original network error attached for debugging
            raise LedgerUnavailableError("Could not reach ledger-core") from exc
        if response.status_code != 200:
            raise LedgerRejectedError(response.status_code)
        return response.json()

    async def accounts(self) -> list[dict]:
        return await self._get("/me/accounts")

    # status: "pending", "completed" or "all"
    async def withdrawals(self, status: str = "all") -> list[dict]:
        return await self._get("/me/withdrawals", params={"status": status})

    # status: a transfer status to filter by; None means all (the parameter is left out)
    async def transfers(self, status: str | None = None) -> list[dict]:
        return await self._get("/me/transfers", params={"status": status} if status else None)

    async def transfer(self, transfer_id: int) -> dict:
        return await self._get(f"/me/transfers/{transfer_id}")
