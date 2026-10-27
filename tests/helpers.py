# A plain helper (not a fixture): logs in and returns the Authorization header
def login_headers(client, email, password="demo1234"):
    response = client.post("/auth/login", json={"email": email, "password": password})
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}