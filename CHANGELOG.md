# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.1] - 2026-04-06

### Added

- Add `platform_name` field to `Sub` model for selecting optimal sender strategy
- Add `ChannelInfo` and `NotifierContext` DTOs to encapsulate notification metadata
- Add global `set_bot_self_id_provider` mechanism to dynamically resolve bot self_id

### Changed

- Refactor session_id construction to use `event.unified_msg_origin` instead of custom function
- Refactor sender selection to use `platform_name` field instead of session_id prefix matching
- AiocqhttpMessageSender now uses feed title as nickname for merged forward nodes

### Fixed

- Fix SQLAlchemy nested session transaction error in monitor loop
- Fix message sending failure caused by incorrect platform identifier in target_session

### Removed

- Remove `get_session_id` utility function (use `event.unified_msg_origin` instead)
- Remove `get_sender_for_session` function (use `get_sender_for_platform_name` instead)
- Remove `bot_self_id` database field (dynamically resolved via provider instead)
