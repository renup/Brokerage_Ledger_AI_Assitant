# A plain helper (not a fixture): logs in and returns the Authorization header
def login_headers(client, email, password="demo1234"):
    response = client.post("/auth/login", json={"email": email, "password": password})
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# A stand-in for the tool router that offers every tool and makes no model call. Chat tests that are
# about something else (tools, memory, proposals) use it so the router's own model call does not
# disturb their scripted model; the real router is tested in test_tool_router.py.
class NoRouting:
    async def registry_for_message(self, messages, registry):
        return registry
