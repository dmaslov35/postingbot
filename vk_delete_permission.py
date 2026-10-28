from dataclasses import dataclass


@dataclass(frozen=True)
class DeleteDecision:
    allowed: bool
    reason: str


def check_delete_permission(
    *,
    publication_verified: bool,
    account_matches: bool,
    owner_matches: bool,
    post_matches: bool,
    vk_can_delete: bool,
) -> DeleteDecision:
    checks = (
        (publication_verified, "PUBLICATION_NOT_VERIFIED"),
        (account_matches, "ACCOUNT_MISMATCH"),
        (owner_matches, "OWNER_MISMATCH"),
        (post_matches, "POST_MISMATCH"),
        (vk_can_delete, "VK_DELETE_PERMISSION_NOT_CONFIRMED"),
    )

    for passed, reason in checks:
        if passed is not True:
            return DeleteDecision(False, reason)

    return DeleteDecision(True, "ALL_CHECKS_PASSED")
