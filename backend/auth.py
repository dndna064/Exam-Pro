import jwt, uuid
from datetime import datetime, timedelta
from functools import wraps
from flask import request, jsonify, current_app

def generate_token(user_id: str, role: str) -> dict:
    expires = datetime.utcnow() + timedelta(hours=current_app.config["JWT_EXPIRES_HOURS"])
    payload = {"sub": user_id, "role": role, "iat": datetime.utcnow(), "exp": expires, "jti": str(uuid.uuid4())}
    token = jwt.encode(payload, current_app.config["JWT_SECRET_KEY"], algorithm="HS256")
    return {"access_token": token, "expires_at": expires.isoformat()}

def decode_token(token: str) -> dict:
    return jwt.decode(token, current_app.config["JWT_SECRET_KEY"], algorithms=["HS256"])

def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "Missing or invalid Authorization header"}), 401
        token = auth_header.split(" ", 1)[1]
        try:
            payload = decode_token(token)
        except jwt.ExpiredSignatureError:
            return jsonify({"error": "Token expired"}), 401
        except jwt.InvalidTokenError:
            return jsonify({"error": "Invalid token"}), 401
        request.current_user = {"id": payload["sub"], "role": payload["role"]}
        return f(*args, **kwargs)
    return decorated

def roles_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            user = getattr(request, "current_user", {})
            if user.get("role") not in roles:
                return jsonify({"error": "Forbidden: insufficient role"}), 403
            return f(*args, **kwargs)
        return decorated
    return decorator
