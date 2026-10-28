
"""Безопасный наблюдатель сетевых ответов VK.

Не отправляет запросы и не подтверждает авторство публикаций.
"""

from urllib.parse import urlparse


class VKNetworkObserver:
    def __init__(self):
        self.events = []

    def handle_response(self, response):
        try:
            parsed = urlparse(response.url)

            host = (parsed.hostname or "").lower()

            if host not in (
                "vk.com",
                "www.vk.com",
                "vk.ru",
                "www.vk.ru",
                "api.vk.com",
            ):
                return

            request = response.request

            if request.method.upper() != "POST":
                return

            status = int(response.status)

            # Не сохраняем URL, параметры запроса,
            # заголовки, тело запроса или ответа.
            event = {
                "host": host,
                "method": "POST",
                "http_status": status,
                "response_ok": 200 <= status < 300,
                "publication_verified": False,
            }

            self.events.append(event)

        except Exception:
            # Наблюдатель не должен прерывать работу браузера.
            return

    def summary(self):
        return {
            "responses_seen": len(self.events),
            "publication_verified": False,
        }
