import json
import urllib.request
from jose import jwt, JWTError

# ── CONFIG ────────────────────────────────────────────────
REGION        = "ap-southeast-2"
USER_POOL_ID  = "ap-southeast-2_VJ2fhcUc7"
CLIENT_ID     = "ueh2ft2l8ap6ccrmk5tcjfsua"
JWKS_URL      = f"https://cognito-idp.{REGION}.amazonaws.com/{USER_POOL_ID}/.well-known/jwks.json"
ISSUER        = f"https://cognito-idp.{REGION}.amazonaws.com/{USER_POOL_ID}"
# ─────────────────────────────────────────────────────────

# Cache the public keys so we don't fetch them on every request
_jwks_cache = None

def get_jwks():
    """Fetch Cognito's public keys (cached after first call)."""
    global _jwks_cache
    if _jwks_cache is None:
        with urllib.request.urlopen(JWKS_URL) as response:
            _jwks_cache = json.loads(response.read())
    return _jwks_cache


def verify_token(token: str) -> dict:
    """
    Verify a Cognito JWT token.

    Returns the decoded token payload (user info) if valid.
    Raises ValueError with a clear message if invalid.

    Usage:
        payload = verify_token(token)
        user_email = payload["email"]
        user_id    = payload["sub"]
    """
    if not token:
        raise ValueError("No token provided")

    # Strip 'Bearer ' prefix if present
    if token.startswith("Bearer "):
        token = token[7:]

    try:
        jwks = get_jwks()

        payload = jwt.decode(
            token,
            jwks,
            algorithms=["RS256"],
            audience=CLIENT_ID,
            issuer=ISSUER,
            options={"verify_exp": True}
        )

        # Extra check: make sure this is an ID token (not access token)
        if payload.get("token_use") != "id":
            raise ValueError("Wrong token type — must be an ID token")

        return payload

    except JWTError as e:
        raise ValueError(f"Invalid token: {str(e)}")


def get_user_from_request(request_headers: dict) -> dict:
    """
    Convenience function — extracts and verifies token from request headers.

    Usage in a GCP Cloud Function:
        user = get_user_from_request(request.headers)
        print(user["email"])
    """
    auth_header = request_headers.get("Authorization") or request_headers.get("authorization")
    if not auth_header:
        raise ValueError("Missing Authorization header")

    return verify_token(auth_header)