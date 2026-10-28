import os
import hmac
import time
import secrets
from aiohttp import web

HOST = "127.0.0.1"
PORT = 8765

TOKEN = os.environ.get("VK_AUTH_GATEWAY_TOKEN", "")
EXPIRES = int(os.environ.get("VK_AUTH_GATEWAY_EXPIRES", "0"))

def authorized(request):
    supplied = request.query.get("token", "")
    return (
        bool(TOKEN)
        and time.time() < EXPIRES
        and hmac.compare_digest(supplied, TOKEN)
    )

async def index(request):
    if not authorized(request):
        raise web.HTTPForbidden(text="Доступ запрещён")

    return web.Response(
        text="🔐 Доступ подтверждён. Шлюз авторизации VK работает.",
        content_type="text/plain",
        charset="utf-8",
    )

async def health(request):
    return web.json_response({"status": "ok"})

app = web.Application()
app.router.add_get("/", index)
app.router.add_get("/health", health)

if __name__ == "__main__":
    web.run_app(app, host=HOST, port=PORT)

async def websocket_test(request):
    if not authorized(request):
        raise web.HTTPForbidden(text="Доступ запрещён")

    ws = web.WebSocketResponse()
    await ws.prepare(request)

    await ws.send_str("AUTHORIZED")
    await ws.close()
    return ws

app.router.add_get("/ws-test", websocket_test)
