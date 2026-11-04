import base64
import hashlib
import hmac
import secrets
import time
from collections import defaultdict, deque
from fastapi import HTTPException, Request
from .config import settings

attempts = defaultdict(deque)

def check_login(request, password):
    key = request.client.host if request.client else 'unknown'
    bucket = attempts[key]
    current = time.monotonic()
    while bucket and bucket[0] < current - 60:
        bucket.popleft()
    if len(bucket) >= 5:
        raise HTTPException(429, '登录尝试过多，请一分钟后重试')
    bucket.append(current)
    if not secrets.compare_digest(password.encode(), settings().admin_password.encode()):
        raise HTTPException(401, '密码错误')
    bucket.clear()

def token():
    payload = f'{int(time.time()) + settings().session_hours * 3600}:{secrets.token_hex(16)}'
    signature = hmac.new(settings().session_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f'{payload}:{signature}'.encode()).decode()

def require_user(request: Request):
    try:
        payload = base64.urlsafe_b64decode(request.cookies.get('session', '')).decode()
        expiry, nonce, signature = payload.split(':')
        expected = hmac.new(settings().session_secret.encode(), f'{expiry}:{nonce}'.encode(), hashlib.sha256).hexdigest()
        if int(expiry) <= time.time() or not hmac.compare_digest(signature, expected):
            raise ValueError()
    except (ValueError, UnicodeError):
        raise HTTPException(401, '请先登录')
    return 'admin'
