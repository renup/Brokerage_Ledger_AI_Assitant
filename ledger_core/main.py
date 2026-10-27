from fastapi import FastAPI

from ledger_core.routers import accounts, login, me, transfers, withdrawals

# The app. The title shows at the top of the /docs page.
app = FastAPI(title="ledger-core")

# Plug each router in. main.py only wires things together; the endpoints
# themselves live in ledger_core/routers/, one file per resource.
app.include_router(login.router)
app.include_router(me.router)
app.include_router(accounts.router)
app.include_router(withdrawals.router)
app.include_router(transfers.router)


# A cheap way for people and tools to ask "is the service up?"
@app.get("/health")
def health():
    # A Python dict that FastAPI turns into JSON
    return {"status": "ok"}
