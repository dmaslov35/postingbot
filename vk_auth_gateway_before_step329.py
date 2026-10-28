import os
import time
import hmac
import secrets
import hashlib
from aiohttp import web

HOST = "127.0.0.1"
PORT = 8765

TOKEN = os.environ.get("VK_AUTH_GATEWAY_TOKEN", "")
EXPIRES = int(os.environ.get("VK_AUTH_GATEWAY_EXPIRES", "0"))

SESSION_LIFETIME = 900
sessions = {}
used_tokens = set()

def valid_token(token):
    return (
        bool(TOKEN)
        and bool(token)
        and time.time() < EXPIRES
        and hmac.compare_digest(token, TOKEN)
    )

def authorized(request):
    session = request.cookies.get("vk_auth_session", "")
    if not session:
        return False

    digest = hashlib.sha256(session.encode()).hexdigest()
    expires = sessions.get(digest, 0)

    return time.time() < expires

async def login(request):
    token = request.query.get("token", "")
    digest = hashlib.sha256(token.encode()).hexdigest()

    if not valid_token(token) or digest in used_tokens:
        raise web.HTTPForbidden(text="Ссылка недействительна")

    used_tokens.add(digest)

    session = secrets.token_urlsafe(32)
    session_digest = hashlib.sha256(session.encode()).hexdigest()
    sessions[session_digest] = min(
        time.time() + SESSION_LIFETIME,
        EXPIRES
    )

    response = web.HTTPFound("/")
    response.set_cookie(
        "vk_auth_session",
        session,
        httponly=True,
        secure=True,
        samesite="Strict",
        max_age=SESSION_LIFETIME,
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    raise response

async def index(request):
    if not authorized(request):
        raise web.HTTPForbidden(text="Доступ запрещён")

    return web.Response(
        text="🔐 Защищённая сессия активна.",
        content_type="text/plain",
        charset="utf-8",
        headers={"Cache-Control": "no-store"},
    )

async def websocket_test(request):
    if not authorized(request):
        raise web.HTTPForbidden(text="Доступ запрещён")

    ws = web.WebSocketResponse()
    await ws.prepare(request)
    await ws.send_str("AUTHORIZED")
    await ws.close()
    return ws

async def health(request):
    return web.json_response({"status": "ok"})

app = web.Application()
app.router.add_get("/login", login)
app.router.add_get("/", index)
app.router.add_get("/ws-test", websocket_test)
app.router.add_get("/health", health)

if __name__ == "__main__":
    web.run_app(app, host=HOST, port=PORT)
