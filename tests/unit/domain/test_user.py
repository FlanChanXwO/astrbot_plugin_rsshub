from __future__ import annotations

from astrbot_plugin_rsshub.src.domain.entities.user import User
from astrbot_plugin_rsshub.src.shared.constants import (
    INHERIT_VALUE,
    USER_STATE_BANNED,
    USER_STATE_USER,
)


def test_user_status_contract_only_distinguishes_user_and_banned():
    user = User(id="u1")

    assert user.state == USER_STATE_USER
    assert user.is_active() is True
    assert user.is_admin() is False

    user.deactivate()
    assert user.state == USER_STATE_BANNED
    assert user.is_active() is False

    user.activate()
    assert user.state == USER_STATE_USER
    assert user.is_active() is True


def test_legacy_non_negative_user_states_are_treated_as_user_not_admin():
    for legacy_state in (0, 100):
        user = User(id=f"u{legacy_state}", state=legacy_state)

        assert user.is_active() is True
        assert user.is_admin() is False


def test_user_profile_options_default_to_inherit_value():
    user = User(id="u1")

    assert user.interval == INHERIT_VALUE
    assert user.notify == INHERIT_VALUE
    assert user.send_mode == INHERIT_VALUE
    assert user.display_media == INHERIT_VALUE
    assert user.get_effective_option("send_mode") is None
