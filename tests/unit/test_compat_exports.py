"""Compatibility export map drift tests."""

from __future__ import annotations

from importlib import import_module
from types import ModuleType
from typing import Any

import pytest

EXPORT_PACKAGES = [
    "astrbot_plugin_rsshub.src.application.services",
    "astrbot_plugin_rsshub.src.infrastructure",
]


def _resolve_export_target(package: ModuleType, name: str, target: Any) -> Any:
    if isinstance(target, tuple):
        module_name, attr_name = target
    else:
        module_name, attr_name = target, name

    module = import_module(f".{module_name}", package.__name__)
    return getattr(module, attr_name)


@pytest.mark.parametrize("package_name", EXPORT_PACKAGES)
def test_lazy_export_map_matches_real_module_exports(package_name: str) -> None:
    package = import_module(package_name)

    assert sorted(package._EXPORT_MAP) == package.__all__

    for name, target in package._EXPORT_MAP.items():
        expected = _resolve_export_target(package, name, target)

        assert getattr(package, name) is expected


def test_subscription_card_management_service_is_a_public_application_export() -> None:
    services = import_module("astrbot_plugin_rsshub.src.application.services")

    exported = services.SubscriptionCardManagementService

    implementation = import_module(
        "astrbot_plugin_rsshub.src.application.services.subscription_card_management_service"
    )
    assert exported is implementation.SubscriptionCardManagementService
