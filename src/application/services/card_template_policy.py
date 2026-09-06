"""卡片模板选择的应用层校验。"""

from __future__ import annotations

from collections.abc import Sequence

from ...domain.entities.bundle import Bundle
from ...domain.entities.card_template import CardTemplateMetadata
from ...domain.entities.subscription import Subscription
from ...domain.exceptions import ValidationError


def validate_card_template_selection(
    *,
    owner: Subscription | Bundle,
    template: CardTemplateMetadata | None,
    feed_urls: Sequence[str],
) -> None:
    """验证 owner 开启卡片时的模板选择。"""
    if not owner.send_card:
        return
    selected_template_id = str(owner.template_id or "").strip()
    if not selected_template_id:
        raise ValidationError("template_id", "send_card=true requires a template")
    if template is None:
        raise ValidationError("template_id", "selected template was not found")
    if template.id != selected_template_id:
        raise ValidationError(
            "template_id",
            "resolved template does not match selected template_id",
        )
    owner_type = "subscription" if isinstance(owner, Subscription) else "bundle"
    if not template.matches_owner(owner_type=owner_type, feed_urls=feed_urls):
        raise ValidationError(
            "template_id",
            "selected template does not support this owner or its feeds",
        )
