"""Configuration parsers and validators."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# 布尔值解析支持的各种格式
BOOL_TRUE_VALUES = {"true", "1", "yes", "y", "on", "enable"}
BOOL_FALSE_VALUES = {"false", "0", "no", "n", "off", "disable"}


def parse_bool_value(value: str) -> bool:
    """Parse boolean value from various formats.

    Supports: true/false, yes/no, y/n, 1/0, on/off, enable/disable

    Args:
        value: String value to parse

    Returns:
        Parsed boolean value

    Raises:
        ValueError: If value is not a valid boolean representation
    """
    lowered = value.strip().lower()
    if lowered in BOOL_TRUE_VALUES:
        return True
    if lowered in BOOL_FALSE_VALUES:
        return False
    raise ValueError(
        f"无效的布尔值: {value}\n"
        f"支持的格式: true/false, yes/no, y/n, 1/0, on/off, enable/disable"
    )


class FieldDescriptionLoader:
    """Load field descriptions from JSON file."""

    _instance: FieldDescriptionLoader | None = None
    _descriptions: dict[str, Any] | None = None

    def __new__(cls) -> FieldDescriptionLoader:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def load(self) -> dict[str, Any]:
        """Load field descriptions from JSON file.

        Returns:
            Dictionary containing field descriptions
        """
        if self._descriptions is not None:
            return self._descriptions

        config_path = (
            Path(__file__).parent.parent / "config" / "field_descriptions.json"
        )
        try:
            with open(config_path, encoding="utf-8") as f:
                self._descriptions = json.load(f)
        except FileNotFoundError:
            self._descriptions = {
                "sub_fields": {},
                "user_fields": {},
                "session_fields": {},
            }
        except json.JSONDecodeError:
            self._descriptions = {
                "sub_fields": {},
                "user_fields": {},
                "session_fields": {},
            }

        return self._descriptions

    def get_sub_field(self, field_name: str) -> dict[str, Any] | None:
        """Get description for a subscription field."""
        descriptions = self.load()
        return descriptions.get("sub_fields", {}).get(field_name)

    def get_user_field(self, field_name: str) -> dict[str, Any] | None:
        """Get description for a user field."""
        descriptions = self.load()
        return descriptions.get("user_fields", {}).get(field_name)

    def get_session_field(self, field_name: str) -> dict[str, Any] | None:
        """Get description for a session field."""
        descriptions = self.load()
        return descriptions.get("session_fields", {}).get(field_name)

    def get_all_sub_fields(self) -> dict[str, Any]:
        """Get all subscription field descriptions."""
        return self.load().get("sub_fields", {})

    def get_all_user_fields(self) -> dict[str, Any]:
        """Get all user field descriptions."""
        return self.load().get("user_fields", {})

    def get_all_session_fields(self) -> dict[str, Any]:
        """Get all session field descriptions."""
        return self.load().get("session_fields", {})

    def format_field_info(
        self, field_name: str, field_def: dict[str, Any], current_value: Any = None
    ) -> str:
        """Format field information for display.

        Args:
            field_name: Name of the field
            field_def: Field definition dictionary
            current_value: Current value of the field

        Returns:
            Formatted field information string
        """
        lines = [
            f"{field_name} = {current_value if current_value is not None else field_def.get('default', 'null')}"
        ]
        lines.append(f"  描述: {field_def.get('description', '')}")

        if "type" in field_def:
            lines.append(f"  类型: {field_def['type']}")

        if "unit" in field_def:
            lines.append(f"  单位: {field_def['unit']}")

        if "values" in field_def:
            lines.append("  可选值:")
            for key, desc in field_def["values"].items():
                lines.append(f"    {key}: {desc}")

        return "\n".join(lines)


# 全局实例
field_loader = FieldDescriptionLoader()
