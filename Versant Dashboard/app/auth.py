"""
Authentication middleware.
- ENVIRONMENT=development: all requests treated as Admin, no login required.
- ENVIRONMENT=production:  Azure AD session required; redirects to /auth/login.
"""
from fastapi import Request, HTTPException, Depends
from fastapi.responses import RedirectResponse
from app.config import settings

DEV_USER = {"name": "Dev User", "email": "dev@local", "roles": ["Admin"]}


async def require_auth(request: Request) -> dict:
    if settings.environment == "development":
        return DEV_USER

    user = request.session.get("user")
    if not user:
        # HTMX partial requests get a 401 (handled in JS); full pages redirect
        if request.headers.get("HX-Request"):
            raise HTTPException(status_code=401, detail="Session expired — please refresh.")
        return RedirectResponse(url="/auth/login")
    return user


def require_role(*roles: str):
    """Factory that returns a Depends-compatible checker for specific roles."""
    async def checker(user: dict = Depends(require_auth)):
        user_roles = user.get("roles", [])
        if not any(r in user_roles for r in roles):
            raise HTTPException(status_code=403, detail="Insufficient permissions.")
        return user
    return checker
