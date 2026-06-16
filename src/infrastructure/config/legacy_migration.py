"""Legacy AstrBot config shape migration helpers."""


def record_config_heal(changes: list[str], path: str, reason: str) -> None:
    changes.append(f"{path}: {reason}")
