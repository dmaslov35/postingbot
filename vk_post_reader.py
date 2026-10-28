from vk_post_identity import extract_post_identity


def read_post_evidence(page, post_url):
    """Читает видимые данные записи из уже открытой страницы.

    Не выполняет переходы по ссылкам и не изменяет страницу.
    Результат НЕ является подтверждением публикации.
    """
    identity = extract_post_identity(post_url)

    if identity is None:
        return {
            "read_ok": False,
            "reason": "INVALID_POST_URL",
        }

    result = {
        "read_ok": False,
        "reason": "NOT_FOUND",
        "vk_post_id": identity["vk_post_id"],
        "post_url": identity["post_url"],
        "actual_text": None,
        "published_at": None,
        "author_verified": False,
    }

    try:
        posts = page.locator(
            f'div[data-post-id="{identity["vk_post_id"]}"]'
        )

        if posts.count() != 1:
            return result

        post = posts.first

        text_selectors = [
            ".wall_post_text",
            ".post_text",
            "[data-testid='post_text']",
        ]

        for selector in text_selectors:
            elements = post.locator(selector)

            if elements.count() > 0:
                text = elements.first.inner_text(timeout=3000)

                if text.strip():
                    result["actual_text"] = text
                    break

        result["read_ok"] = result["actual_text"] is not None

        if result["read_ok"]:
            result["reason"] = "TEXT_EXTRACTED"

    except Exception:
        result["reason"] = "READ_ERROR"

    return result


def validate_read_post_evidence(evidence, expected_post_id, expected_text):
    """Проверяет совпадение записи без подтверждения авторства."""
    result = {
        "matched": False,
        "author_verified": False,
        "deletion_authorized": False,
        "reason": "POST_EVIDENCE_MISMATCH",
    }

    if not isinstance(evidence, dict):
        result["reason"] = "INVALID_POST_EVIDENCE"
        return result

    if evidence.get("read_ok") is not True:
        result["reason"] = "POST_READ_FAILED"
        return result

    if (
        not isinstance(expected_post_id, str)
        or not expected_post_id
        or not isinstance(expected_text, str)
        or not expected_text.strip()
    ):
        result["reason"] = "INVALID_EXPECTED_POST"
        return result

    if (
        evidence.get("vk_post_id") != expected_post_id
        or evidence.get("actual_text") != expected_text
    ):
        return result

    result["matched"] = True
    result["reason"] = "POST_ID_AND_TEXT_MATCH"
    return result


def match_network_proof_to_wall(
    network_proof, wall_items, expected_owner_id, expected_text
):
    """Сопоставляет сетевой post_id с записью на стене без подтверждения авторства."""
    result = {
        "matched": False,
        "author_verified": False,
        "deletion_authorized": False,
        "vk_post_id": None,
        "reason": "NO_MATCH",
    }

    if (
        not isinstance(network_proof, dict)
        or network_proof.get("matched") is not True
        or type(network_proof.get("post_id")) is not int
        or network_proof["post_id"] <= 0
        or type(expected_owner_id) is not int
        or expected_owner_id >= 0
        or not isinstance(expected_text, str)
        or not expected_text.strip()
        or not isinstance(wall_items, list)
    ):
        result["reason"] = "INVALID_EVIDENCE"
        return result

    post_id = network_proof["post_id"]
    full_id = f"{expected_owner_id}_{post_id}"

    matches = [
        item for item in wall_items
        if isinstance(item, dict)
        and type(item.get("owner_id")) is int
        and item["owner_id"] == expected_owner_id
        and type(item.get("id")) is int
        and item["id"] == post_id
        and item.get("text") == expected_text
    ]

    if len(matches) != 1:
        result["reason"] = (
            "DUPLICATE_MATCH" if len(matches) > 1
            else "POST_NOT_MATCHED"
        )
        return result

    result["matched"] = True
    result["vk_post_id"] = full_id
    result["reason"] = "NETWORK_AND_WALL_MATCH"
    return result


def check_saved_publication_against_wall(
    network_proof, wall_response, owner_id, expected_text
):
    """Проверяет сохранённый сетевой ID по данным стены без подтверждения авторства."""
    if not isinstance(wall_response, dict):
        return {
            "matched": False,
            "author_verified": False,
            "deletion_authorized": False,
            "vk_post_id": None,
            "reason": "INVALID_WALL_RESPONSE",
        }

    return match_network_proof_to_wall(
        network_proof=network_proof,
        wall_items=wall_response.get("items"),
        expected_owner_id=owner_id,
        expected_text=expected_text,
    )


def check_read_wall_posts_against_network(
    network_proof, posts, owner_id, expected_text
):
    """Сопоставляет результат read_wall_posts с сетевым доказательством."""
    if not isinstance(posts, list):
        posts = None

    items = []

    if posts is not None:
        for post in posts:
            if not isinstance(post, dict):
                continue

            identity = extract_post_identity(post.get("post_url"))

            if not isinstance(identity, dict):
                continue

            full_id = identity.get("vk_post_id")

            if not isinstance(full_id, str):
                continue

            parts = full_id.split("_")

            if len(parts) != 2:
                continue

            try:
                parsed_owner = int(parts[0])
                parsed_post = int(parts[1])
            except ValueError:
                continue

            if parsed_owner >= 0 or parsed_post <= 0:
                continue

            items.append({
                "owner_id": parsed_owner,
                "id": parsed_post,
                "text": post.get("text"),
            })

    return check_saved_publication_against_wall(
        network_proof,
        {"items": items} if posts is not None else None,
        owner_id,
        expected_text,
    )
