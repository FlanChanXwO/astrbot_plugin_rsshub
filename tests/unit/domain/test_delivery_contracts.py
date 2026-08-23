from __future__ import annotations

from datetime import datetime, timezone

import pytest
from astrbot_plugin_rsshub.src.application.dto.subscription_dto import SubscriptionDTO
from astrbot_plugin_rsshub.src.application.services.card_template_policy import (
    validate_card_template_selection,
)
from astrbot_plugin_rsshub.src.domain.entities.bundle import Bundle
from astrbot_plugin_rsshub.src.domain.entities.card_template import CardTemplateMetadata
from astrbot_plugin_rsshub.src.domain.entities.subscription import Subscription
from astrbot_plugin_rsshub.src.domain.exceptions import (
    ValidationError as DomainValidationError,
)
from astrbot_plugin_rsshub.src.shared.constants import INHERIT_VALUE
from pydantic import ValidationError


def make_template_metadata(**overrides: object) -> CardTemplateMetadata:
    payload = {
        "id": "astrbot_plugin_rsshub_card_generic",
        "name": "Generic Daily",
        "version": "1.0.0",
        "author": "Example Author",
        "description": "A generic card.",
        "repository": "https://example.com/templates/generic",
        "targets": ["feed", "bundle"],
    }
    payload.update(overrides)
    return CardTemplateMetadata.model_validate(payload)


def test_subscription_card_settings_have_backward_compatible_defaults() -> None:
    subscription = Subscription(user_id="user-1", feed_id=1)

    assert subscription.send_card is False
    assert subscription.template_id is None
    assert subscription.card_send_original_content is False
    assert subscription.model_dump()["send_card"] is False
    assert subscription.model_dump()["template_id"] is None
    assert subscription.model_dump()["card_send_original_content"] is False


def test_subscription_dto_serializes_card_settings() -> None:
    now = datetime.now(timezone.utc)
    dto = SubscriptionDTO(
        user_id="user-1",
        feed_id=1,
        created_at=now,
        updated_at=now,
        send_card=True,
        template_id="astrbot_plugin_rsshub_card_generic",
        card_send_original_content=True,
    )

    assert dto.model_dump()["send_card"] is True
    assert dto.model_dump()["template_id"] == "astrbot_plugin_rsshub_card_generic"
    assert dto.model_dump()["card_send_original_content"] is True


def test_bundle_card_settings_have_the_same_defaults_as_subscription() -> None:
    bundle = Bundle(
        user_id="user-1",
        name="Daily digest",
        target_sessions=["test:Group:1"],
        interval=30,
    )

    assert bundle.send_card is False
    assert bundle.template_id is None
    assert bundle.card_send_original_content is False
    assert bundle.model_dump()["send_card"] is False
    assert bundle.model_dump()["template_id"] is None
    assert bundle.model_dump()["card_send_original_content"] is False


def test_bundle_serialization_exposes_stable_delivery_defaults() -> None:
    bundle = Bundle(
        user_id="user-1",
        name="Daily digest",
        target_sessions=[" test:Group:1 ", "test:Group:2", "test:Group:1"],
        interval=30,
    )

    assert bundle.target_sessions == ["test:Group:1", "test:Group:2"]
    assert bundle.state == 0
    assert bundle.next_check_time is None
    assert bundle.notify == INHERIT_VALUE
    assert bundle.send_mode == INHERIT_VALUE
    assert bundle.length_limit == INHERIT_VALUE
    assert bundle.display_author == INHERIT_VALUE
    assert bundle.display_via == INHERIT_VALUE
    assert bundle.display_title == INHERIT_VALUE
    assert bundle.display_entry_tags == INHERIT_VALUE
    assert bundle.style == INHERIT_VALUE
    assert bundle.display_media == INHERIT_VALUE
    assert bundle.handlers == []
    assert bundle.model_dump(by_alias=True)["handlers"] == []


@pytest.mark.parametrize("field_name", ["handlers", "handler_specs"])
def test_bundle_normalizes_handlers_from_alias_or_field_name(field_name: str) -> None:
    raw_handlers = [
        {
            "id": " external.custom.default ",
            "type": "external",
            "name": "custom",
            "status": 1,
            "config": {},
        }
    ]

    bundle = Bundle(
        user_id="user-1",
        name="Daily digest",
        target_sessions=["test:Group:1"],
        interval=30,
        **{field_name: raw_handlers},
    )

    assert bundle.handlers[0]["id"] == "external.custom.default"
    assert bundle.model_dump(by_alias=True)["handlers"] == bundle.handlers


@pytest.mark.parametrize("state", [-1, 2])
def test_bundle_rejects_unknown_runtime_states(state: int) -> None:
    with pytest.raises(ValidationError, match="state"):
        Bundle(
            user_id="user-1",
            name="Daily digest",
            target_sessions=["test:Group:1"],
            interval=30,
            state=state,
        )


def test_delivery_contracts_are_exported_by_the_domain_package() -> None:
    from astrbot_plugin_rsshub.src.domain import (
        Bundle as ExportedBundle,
    )
    from astrbot_plugin_rsshub.src.domain import (
        CardTemplateMetadata as ExportedCardTemplateMetadata,
    )

    assert ExportedBundle is Bundle
    assert ExportedCardTemplateMetadata is CardTemplateMetadata


def test_card_template_policy_requires_template_id_when_card_is_enabled() -> None:
    subscription = Subscription(
        user_id="user-1",
        feed_id=1,
        send_card=True,
    )

    with pytest.raises(DomainValidationError, match="template_id"):
        validate_card_template_selection(
            owner=subscription,
            template=None,
            feed_urls=["https://example.com/feed"],
        )


def test_card_template_policy_requires_the_selected_template_to_exist() -> None:
    subscription = Subscription(
        user_id="user-1",
        feed_id=1,
        send_card=True,
        template_id="astrbot_plugin_rsshub_card_missing",
    )

    with pytest.raises(DomainValidationError, match="not found"):
        validate_card_template_selection(
            owner=subscription,
            template=None,
            feed_urls=["https://example.com/feed"],
        )


def test_card_template_policy_rejects_a_different_template_than_selected() -> None:
    subscription = Subscription(
        user_id="user-1",
        feed_id=1,
        send_card=True,
        template_id="astrbot_plugin_rsshub_card_selected",
    )

    with pytest.raises(DomainValidationError, match="does not match selected"):
        validate_card_template_selection(
            owner=subscription,
            template=make_template_metadata(id="astrbot_plugin_rsshub_card_other"),
            feed_urls=["https://example.com/feed"],
        )


@pytest.mark.parametrize(
    ("targets", "feed_patterns"),
    [
        (["bundle"], []),
        (["feed"], [r"other\.example/rss$"]),
    ],
)
def test_card_template_policy_requires_owner_and_feeds_to_match(
    targets: list[str],
    feed_patterns: list[str],
) -> None:
    template_id = "astrbot_plugin_rsshub_card_selected"
    subscription = Subscription(
        user_id="user-1",
        feed_id=1,
        send_card=True,
        template_id=template_id,
    )

    with pytest.raises(DomainValidationError, match="does not support"):
        validate_card_template_selection(
            owner=subscription,
            template=make_template_metadata(
                id=template_id,
                targets=targets,
                feed_patterns=feed_patterns,
            ),
            feed_urls=["https://example.com/feed"],
        )


def test_card_template_policy_accepts_valid_and_disabled_owners() -> None:
    subscription_template = make_template_metadata(
        id="astrbot_plugin_rsshub_card_feed",
        targets=["feed"],
        feed_patterns=[r"example\.com/feed$"],
    )
    subscription = Subscription(
        user_id="user-1",
        feed_id=1,
        send_card=True,
        template_id=subscription_template.id,
    )
    validate_card_template_selection(
        owner=subscription,
        template=subscription_template,
        feed_urls=["https://example.com/feed"],
    )

    bundle_template = make_template_metadata(
        id="astrbot_plugin_rsshub_card_bundle",
        targets=["bundle"],
        feed_patterns=[r"example\.com/(news|blog)$"],
    )
    bundle = Bundle(
        user_id="user-1",
        name="Daily digest",
        target_sessions=["test:Group:1"],
        interval=30,
        send_card=True,
        template_id=bundle_template.id,
    )
    validate_card_template_selection(
        owner=bundle,
        template=bundle_template,
        feed_urls=["https://example.com/news", "https://example.com/blog"],
    )

    validate_card_template_selection(
        owner=Subscription(user_id="user-1", feed_id=2),
        template=None,
        feed_urls=[],
    )


def test_card_template_metadata_accepts_the_complete_minimal_contract() -> None:
    metadata = CardTemplateMetadata(
        id="astrbot_plugin_rsshub_card_juya_ai",
        name="Juya AI Daily",
        version="1.2.3",
        author="Example Author",
        description="A daily card for Juya AI feeds.",
        repository="https://example.com/templates/juya-ai",
        targets=["feed"],
    )

    assert metadata.feed_patterns == []
    assert metadata.model_dump() == {
        "id": "astrbot_plugin_rsshub_card_juya_ai",
        "name": "Juya AI Daily",
        "version": "1.2.3",
        "author": "Example Author",
        "description": "A daily card for Juya AI feeds.",
        "repository": "https://example.com/templates/juya-ai",
        "targets": ["feed"],
        "feed_patterns": [],
    }


def test_card_template_metadata_accepts_semver_prerelease_and_build() -> None:
    metadata = make_template_metadata(version="2.0.0-rc.1+build.20260824")

    assert metadata.version == "2.0.0-rc.1+build.20260824"


def test_card_template_metadata_rejects_ids_outside_the_plugin_namespace() -> None:
    with pytest.raises(ValidationError, match="astrbot_plugin_rsshub_card_"):
        make_template_metadata(id="generic_card")


@pytest.mark.parametrize("version", ["1.2", "01.2.3", "1.2.3-"])
def test_card_template_metadata_requires_semver(version: str) -> None:
    with pytest.raises(ValidationError, match="SemVer"):
        make_template_metadata(version=version)


@pytest.mark.parametrize("targets", [[], ["subscription"], ["feed", "other"]])
def test_card_template_metadata_requires_supported_non_empty_targets(
    targets: list[str],
) -> None:
    with pytest.raises(ValidationError, match="targets"):
        make_template_metadata(targets=targets)


@pytest.mark.parametrize("field", ["name", "author", "description", "repository"])
def test_card_template_metadata_rejects_blank_required_text(field: str) -> None:
    with pytest.raises(ValidationError, match=field):
        make_template_metadata(**{field: "   "})


def test_card_template_metadata_rejects_invalid_feed_patterns() -> None:
    with pytest.raises(ValidationError, match="feed_patterns"):
        make_template_metadata(feed_patterns=[r"juya\.ai/feed", "["])


def test_card_template_metadata_rejects_undeclared_package_contract_fields() -> None:
    with pytest.raises(ValidationError, match="schema_version"):
        make_template_metadata(schema_version=1)


def test_card_template_matches_subscription_by_normalized_feed_url() -> None:
    metadata = make_template_metadata(
        targets=["feed"],
        feed_patterns=[r"juya\.ai/rss$"],
    )

    assert metadata.matches_owner(
        owner_type="subscription",
        feed_urls=["HTTPS://JUYA.AI/rss/"],
    )
    assert not metadata.matches_owner(
        owner_type="subscription",
        feed_urls=["https://example.com/rss"],
    )


def test_card_template_requires_every_bundle_feed_to_match() -> None:
    metadata = make_template_metadata(
        targets=["bundle"],
        feed_patterns=[r"example\.com/(news|blog)$"],
    )

    assert metadata.matches_owner(
        owner_type="bundle",
        feed_urls=[
            "https://example.com/news",
            "https://example.com/blog/",
        ],
    )
    assert not metadata.matches_owner(
        owner_type="bundle",
        feed_urls=[
            "https://example.com/news",
            "https://other.example/feed",
        ],
    )
    assert not metadata.matches_owner(
        owner_type="subscription",
        feed_urls=["https://example.com/news"],
    )


def test_empty_feed_patterns_match_any_feed_for_a_supported_target() -> None:
    metadata = make_template_metadata(targets=["feed"], feed_patterns=[])

    assert metadata.matches_owner(
        owner_type="subscription",
        feed_urls=["https://any.example/feed"],
    )


def test_card_template_matching_rejects_unknown_owner_types() -> None:
    metadata = make_template_metadata()

    with pytest.raises(ValueError, match="owner_type"):
        metadata.matches_owner(
            owner_type="feed",  # type: ignore[arg-type]
            feed_urls=["https://example.com/feed"],
        )
