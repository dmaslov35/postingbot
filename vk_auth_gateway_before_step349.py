import os
import time
import hmac
import secrets
import hashlib
import asyncio
from aiohttp import web, WSMsgType
from pathlib import Path

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

    return (
        time.time() < expires
        and time.time() < EXPIRES
    )

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

    response = web.HTTPFound("/vnc.html?autoconnect=1&path=websockify")
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


async def vnc_websocket(request):
    if not authorized(request):
        raise web.HTTPForbidden(text="Доступ запрещён")

    origin = request.headers.get("Origin", "")
    from urllib.parse import urlsplit
    parsed = urlsplit(origin)

    if (
        not origin
        or parsed.scheme != "https"
        or parsed.netloc != request.host
    ):
        raise web.HTTPForbidden(text="Недопустимый источник")

    reader, writer = await asyncio.open_connection("127.0.0.1", 5901)
    ws = web.WebSocketResponse(heartbeat=30)
    await ws.prepare(request)

    async def browser_to_vnc():
        async for msg in ws:
            if msg.type == WSMsgType.BINARY:
                writer.write(msg.data)
                await writer.drain()
            elif msg.type == WSMsgType.TEXT:
                writer.write(msg.data.encode())
                await writer.drain()

    async def vnc_to_browser():
        while not ws.closed:
            if not authorized(request):
                break

            try:
                data = await asyncio.wait_for(reader.read(65536), timeout=2)
            except asyncio.TimeoutError:
                continue

            if not data:
                break

            if not authorized(request):
                break

            await ws.send_bytes(data)

    tasks = [
        asyncio.create_task(browser_to_vnc()),
        asyncio.create_task(vnc_to_browser()),
    ]

    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        writer.close()
        await writer.wait_closed()
        await ws.close()

    return ws


NOVNC_ROOT = Path("/usr/share/novnc").resolve()

async def novnc_files(request):
    if not authorized(request):
        raise web.HTTPForbidden(text="Доступ запрещён")

    relative = request.match_info.get("filepath", "vnc.html")

    if not relative:
        relative = "vnc.html"

    target = (NOVNC_ROOT / relative).resolve()

    if not target.is_relative_to(NOVNC_ROOT) or not target.is_file():
        raise web.HTTPNotFound()

    response = web.FileResponse(target)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


# Локальная выдача одноразовых ссылок для Telegram-бота.
AUTH_SECRET_FILE = Path("/opt/vkbot/runtime/auth/gateway_secret")
issued_tokens = {}

async def issue_auth_link(request):
    global TOKEN, EXPIRES

    if request.remote not in ("127.0.0.1", "::1"):
        raise web.HTTPForbidden(text="Только локальный доступ")

    supplied = request.headers.get("X-Gateway-Secret", "")

    try:
        expected = AUTH_SECRET_FILE.read_text().strip()
    except OSError:
        raise web.HTTPServiceUnavailable(text="Секрет недоступен")

    if not supplied or not hmac.compare_digest(supplied, expected):
        raise web.HTTPForbidden(text="Доступ запрещён")

    try:
        data = await request.json()
        account_id = int(data["account_id"])
    except (ValueError, TypeError, KeyError):
        raise web.HTTPBadRequest(text="Неверный ID аккаунта")

    if account_id <= 0:
        raise web.HTTPBadRequest(text="Неверный ID аккаунта")

    # Одновременно допускается только одна активная ссылка.
    sessions.clear()
    used_tokens.clear()

    TOKEN = secrets.token_urlsafe(32)
    EXPIRES = int(time.time()) + 900

    issued_tokens.clear()
    issued_tokens[account_id] = EXPIRES

    return web.json_response({
        "token": TOKEN,
        "account_id": account_id,
        "expires_in": 900,
        "path": "/login",
    }, headers={"Cache-Control": "no-store"})

app = web.Application()
app.router.add_get("/login", login)
app.router.add_get("/", index)
app.router.add_get("/ws-test", websocket_test)
app.router.add_get("/websockify", vnc_websocket)
app.router.add_get("/health", health)
app.router.add_post("/internal/issue", issue_auth_link)
app.router.add_get("/vnc.html", novnc_files)
app.router.add_get("/{filepath:.+}", novnc_files)

if __name__ == "__main__":
    web.run_app(app, host=HOST, port=PORT)
