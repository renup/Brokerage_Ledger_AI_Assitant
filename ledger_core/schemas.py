from pydantic import BaseModel


# Schemas describe the shape of data going in and out of the API.
# They are not database tables (that's models.py).


# What the caller sends to /auth/login. A missing field gives an automatic 422 error.
class LoginRequest(BaseModel):
    email: str
    password: str


# What /auth/login sends back
class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"  # default, so we don't have to set it each time
    expires_in: int  # seconds until the token expires


# Only these three fields are ever returned for a customer.
# Using this as a response_model is how we make sure password_hash never leaks.
class CustomerPublic(BaseModel):
    id: int
    name: str
    email: str
