
"""Безопасный наблюдатель сетевых ответов VK.

Не отправляет запросы и не подтверждает авторство публикаций.
"""

from urllib.parse import urlparse


class VKNetworkObserver:
    def __init__(
        self,
        expected_owner_id=None,
        expected_text=None,
        queue_id=None,
        account_id=None,
    ):
        self.queue_id = queue_id
        self.account_id = account_id
        self.events = []
        self.active_requests = set()
        self.expected_owner_id = expected_owner_id
        self.expected_text = expected_text

    def handle_request(self, request):
        try:
            parsed = urlparse(request.url)
            if (
                parsed.scheme != "https"
                or (parsed.hostname or "").lower() != "api.vk.com"
                or parsed.path.rstrip("/") != "/method/wall.post"
                or request.method.upper() != "POST"
            ):
                return
            if self.expected_owner_id is None or not isinstance(self.expected_text, str):
                return

            from vk_request_matcher import match_wall_post_request

            match = match_wall_post_request(
                request,
                self.expected_owner_id,
                self.expected_text,
            )

            if not match["matched"]:
                return

            self.active_requests.add(request)
        except Exception:
            pass

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

            if request not in self.active_requests:
                return
            self.active_requests.discard(request)

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

            # Разбираем только точный метод VK API wall.post.
            # Другие ответы не читаем.
            if (
                host == "api.vk.com"
                and parsed.scheme == "https"
                and parsed.path.rstrip("/") == "/method/wall.post"
                and status == 200
            ):
                from vk_post_response_parser import parse_wall_post_response

                payload = response.json()

                parsed_post = parse_wall_post_response(
                    response.url,
                    request.method,
                    status,
                    payload
                )

                if parsed_post["post_id"] is not None:
                    event["post_id"] = parsed_post["post_id"]
                    event["post_id_source"] = "VK_API_WALL_POST"
                    event["publication_verified"] = False

            self.events.append(event)

        except Exception:
            # Наблюдатель не должен прерывать работу браузера.
            return

    def summary(self):
        return {
            "responses_seen": len(self.events),
            "publication_verified": False,
        }


def assess_network_publication(events, queue_id, account_id, flow):
    """Оценивает сетевые доказательства без разрешения на удаление."""
    result = {
        "verified": False,
        "deletion_authorized": False,
        "post_id": None,
        "reason": "INSUFFICIENT_NETWORK_EVIDENCE",
    }

    if (
        type(queue_id) is not int or queue_id <= 0
        or type(account_id) is not int or account_id <= 0
    ):
        result["reason"] = "INVALID_JOB_CONTEXT"
        return result

    if flow not in ("CREATE", "SUGGEST"):
        result["reason"] = "INVALID_PUBLICATION_FLOW"
        return result

    if flow == "SUGGEST":
        result["reason"] = "PENDING_MODERATION_NOT_PUBLICATION"
        return result

    if not isinstance(events, list):
        result["reason"] = "INVALID_EVENTS"
        return result

    candidates = [
        event for event in events
        if isinstance(event, dict)
        and event.get("post_id_source") == "VK_API_WALL_POST"
        and event.get("host") == "api.vk.com"
        and event.get("method") == "POST"
        and event.get("http_status") == 200
        and event.get("response_ok") is True
        and type(event.get("post_id")) is int
        and event["post_id"] > 0
    ]

    if len(events) != 1 or len(candidates) != 1:
        result["reason"] = "AMBIGUOUS_NETWORK_RESPONSE"
        return result

    result["post_id"] = candidates[0]["post_id"]
    result["reason"] = "SINGLE_MATCHED_WALL_POST_RESPONSE"

    # Это подтверждает наличие одного подходящего сетевого ответа,
    # но не устанавливает право на удаление записи.
    return result


def validate_publication_evidence(
    events, queue_id, account_id, flow,
    expected_queue_id, expected_account_id
):
    """Проверяет контекст сетевого доказательства без подтверждения авторства."""
    result = {
        "matched": False,
        "verified": False,
        "deletion_authorized": False,
        "post_id": None,
        "reason": "INSUFFICIENT_EVIDENCE",
    }

    if (
        type(queue_id) is not int or queue_id <= 0
        or type(account_id) is not int or account_id <= 0
        or type(expected_queue_id) is not int or expected_queue_id <= 0
        or type(expected_account_id) is not int or expected_account_id <= 0
    ):
        result["reason"] = "INVALID_CONTEXT"
        return result

    if (
        queue_id != expected_queue_id
        or account_id != expected_account_id
    ):
        result["reason"] = "CONTEXT_MISMATCH"
        return result

    assessment = assess_network_publication(
        events, queue_id, account_id, flow
    )

    result["reason"] = assessment["reason"]

    if (
        flow == "CREATE"
        and assessment["post_id"] is not None
        and assessment["reason"] == "SINGLE_MATCHED_WALL_POST_RESPONSE"
    ):
        result["matched"] = True
        result["post_id"] = assessment["post_id"]

    return result
