# AGENTS.md — astrbot_plugin_rsshub

Repository guide for agent work on this plugin.

## Project overview

- AstrBot RSSHub plugin with DDD layering.
- Entry split is strict: `main.py` (decorators/lifecycle) and `bootstrap.py` (composition/startup).
- Management features belong to Plugin Pages + Web API.

## Communication language

- 与用户沟通必须使用中文。

## Structure

- `src/domain/`: entities, value objects, repository protocols.
- `src/application/`: commands, queries, DTOs, orchestration services.
- `src/infrastructure/`: adapters for config/persistence/fetch/messaging/scheduling/knowledge.
- `src/interfaces/`: command handlers and `web_api.py`.
- `pages/`: Plugin Pages frontend.
- `tests/`: unit/integration suites and fixtures.

## Contribution and documentation constraints

- 本项目允许使用 AI 协作贡献，包括代码、测试、文档、排障与重构准备。
- 修改代码时，不要把文档视为“可选收尾”。如果行为、边界、入口、配置、流程图、架构章节或维护约定已经不再准确，必须在同一改动中更新对应 `docs/`。
- 下列变化默认视为“必须同步文档”：
  - 命令行为或参数变化
  - Web API / Plugin Pages 交互变化
  - 配置项、继承语义、默认值或兼容规则变化
  - handler、AI、sender、KB、push history、queue、dedup 算法变化
  - 仓储查询语义、测试推送路径、失败重试语义变化
- 除更新 `README.md` / `docs/` 外，只要规则、维护约定、架构边界被修改，也必须同步更新 `AGENTS.md` 和 `CLAUDE.md`。

## Recommended AI models

- 后端与核心链路（`src/`、测试、迁移、调度、命令、仓储、sender）优先使用逻辑能力更强的模型：
  - `gpt-5.5`
  - `claude opus 4.7`
  - `glm-5.1`
- 前端 Plugin Pages（`pages/`）可优先使用更擅长前端实现与交互整理的模型：
  - `gemini 3.1 pro`
  - `kimi 2.6`
- 如果希望全栈统一，也推荐直接使用：
  - `gpt-5.5`
  - `claude opus 4.7`
- 模型建议不是强制门禁，但在复杂后端改动上，不建议优先使用逻辑稳定性明显较弱的模型。

## Command surface invariants

Keep these command signatures full-argument (`GreedyStr` compatible):

- `/sub`
- `/unsub`
- `/sub_list`
- `/sub_export`
- `/sub_import`
- `/sub_test`

Behavior invariants:

- `/sub_test <ID|URL>` = real push of the latest entry (not preview); chat command does not accept extra range args.
- `/unsub` supports ID/URL mixed batch semantics.
- `/sub` supports multi-URL batch semantics.
- `/sub_list` supports current-session pagination only (no `all` scope).
- `/sub_export [all]` scope behavior with admin guard.
- `/sub_import` supports TOML path and upload-waiting flow.
- `/sub_status` lists running/queued jobs for current session.
- `/sub_stop [job_id|feed_id|all]` supports precise/批量 stop; no arg stops current running job.
- `/rsshelp` sends pre-generated help image (`assets/help/rsshelp.png`).
- `/rsshub_kb_init`, `/rsshub_kb_sync`, `/rsshub_kb_status`, `/rsshub_kb_task` manage RSSHub Routes KB sync; do not restore route-search LLM tools.

## Push compatibility invariants

- OneBot merged-forward node name: prefer feed title; fallback `RSSHub`.
- Push tail formatting should include legacy `via <link> | <feed> (author: ...)` style.
- Only append all original media URLs when a send failure falls back to text or when recording failure-facing history; successful push content should stay free of extra raw media-link suffixes.
- `style` means push layout policy: `0=auto`, `1=RSSRT`, `2=original`. Legacy `flowerss=1` is removed and migrated to `0`; do not restore flowerss UI wording.
- `qq_official` must combine a single image + text in one chain. In classic style, video/multimedia still sends media before final text. In original style, use parsed layout fragments and pair image + following text when possible.
- `weixin_oc` must never attempt image+text in one message; original style changes order only, not chain combining.
- OneBot auto/classic uses merged-forward and falls back to text-only Nodes after merged-forward failure. OneBot original style sends parsed layout fragments without a large merged-forward package.
- `PushHistory.fail_reason` and sender exception detail must stay within the 512-character model/database limit; repository reads must tolerate and truncate legacy overlong values.
- `send_mode` runtime semantics are `-1=仅链接`、`0=自动`、`1=直接发送`；legacy `1=Telegraph` must normalize to `0` and legacy `2=直接消息` must normalize to `1`.
- Telegraph is a Telegram sender-level auto-routing strategy, not an explicit send mode; it only applies when the Telegram sender enables it and normalized deduplicated media count is greater than 1. Do not expose or execute Telegraph routing for OneBot/QQ Official.
- Telegram local image files larger than 10 MiB must be sent as files instead of photos to avoid Bot API photo size rejection.
- m3u8/HLS pre-download must validate FFmpeg output with ffprobe before caching; reject zero-duration or no-video files and let sender failure fallback expose the original URL.
- Media sending always pre-downloads media before building platform components. Only successful media downloads are cached; do not reintroduce in-memory or disk failure caches, and do not restore a user-facing `download_media_before_send` toggle.
- When title display is disabled, formatter must not remove a body prefix just because it equals the title; repeated-title removal only applies when the title is actually shown.
- `minimal_interval` is a persisted write-time hard floor for subscription/default interval values; do not downgrade it into a runtime-only clamp.
- `failed_queue_capacity=0` disables automatic retry queue pickup only; failed `push_history` records must still be written and kept for audit.
- `failed_queue_max_retries` is the automatic retry ceiling for a `push_history` record; exceeding it stops auto-retry, not failure-history retention.
- `deduplicate_multi_bot` only deduplicates deliveries within the same `target_session` when the final payload is equivalent; suppressed deliveries must persist `push_history.status=skipped` for audit.

## Subscription profile invariants

- `rsshub_sub` and `rsshub_user` do not use `use_sub_config` / `use_user_config`; do not reintroduce those columns or API fields.
- `-100` is the sole inheritance marker for subscription/user profile options. Subscription options inherit from user profile; user profile options inherit from global defaults.
- `rsshub_sub.handlers` and `rsshub_user.handlers` store JSON handler chains. Do not reintroduce `ai_prompt`; legacy non-empty prompts migrate to `builtin.ai_transform`.
- Legacy translation columns (`translate`, `translate_target_lang`) must stay removed from `rsshub_sub` and `rsshub_user`.

## Do-not-regress rules

- Do not reintroduce `/rsshub_admin` or `handle_admin_panel`.
- Do not add `Main` alias.
- Do not move startup ownership out of `bootstrap.py`.
- Do not call `get_astrbot_plugin_data_path()` directly outside `src/infrastructure/utils/paths.py`.
- Local debugging from this plugin directory must not create/use `<plugin>/data` for runtime state; use `get_plugin_data_dir()`, `get_plugin_cache_dir()`, or `get_plugin_export_dir()`.
- `_conf_schema.json` only exposes startup-level config, Routes KB provider/source settings, content handler AI provider/persona selection, credentials, and platform strategies; subscription defaults belong in Plugin Pages.
- Fixed-choice `_conf_schema.json` fields should use `options`; bounded numeric fields should use `slider` instead of free-form numbers.
- Startup config must be self-healed against `_conf_schema.json`: add missing defaults, remove unknown/legacy fields, coerce recoverable numeric values, clamp sliders, and reset invalid options before typed runtime parsing. Any `_conf_schema.json` field add/remove/type change must update config self-heal regression tests.
- `sender_strategies.enabled_platforms` is a list-style platform multi-select in `_conf_schema.json`, but it should only expose platforms with meaningful sender-strategy toggles today: `telegram`, `aiocqhttp`, `qq_official`. Do not add `weixin_oc` back into this list unless WeChat gains a real dedicated strategy surface. `sender_strategies.platform_strategies` is the single `template_list` for platform strategy templates such as `telegram_strategy` and `onebot_strategy`. Runtime reads only the first item for each template type. Template fields may differ by platform; keep OneBot-only fields such as `prefer_local_video` out of the Telegram template and Telegraph fields out of the OneBot template. Keep runtime compatibility for old bool-map, object configs, and legacy per-platform template lists in infrastructure adapters.
- Plugin Pages may manage existing subscriptions, users, push history, subscription defaults, and Routes KB tasks, but must not provide new subscription creation or subscription TOML import/export entry points. Use chat commands or AI agent tools for those user-owned flows.
- Plugin Pages handler editors are schema-driven and shared between user/subscription forms; they should read `handlers/schema` when available, keep a frontend fallback, and preserve raw JSON editing for unknown extension handlers. Builtin handlers only include `ai_filter` and `ai_transform`; HTML/XML 清洗属于基础解析与格式化链，不是可配置 handler. `ai_filter.input_scope` is `text|raw_xml|both`; `ai_transform.scope` is `plaintext|xml`.
- `content_handlers.ai_provider_id` / `ai_persona_id` are global defaults for builtin `ai_filter` and `ai_transform`; API keys remain in AstrBot Provider config, and persona selection only injects a system prompt for handler calls. `ai_filter` stays on direct provider JSON classification; `ai_transform` always runs through AstrBot `tool_loop_agent`.
- Plugin Pages must not expose `link_preview` controls or state.
- Do not add or use a `webadmin` fallback user. Web API endpoints that mutate or export user-owned resources must receive an explicit real `user_id`.
- Do not restore legacy content-processing, translation, AI enrich pipeline settings, or `_conf_schema.json` content pipeline toggles. Current content processing belongs to the handlers chain.
- Formatter responsibilities are formatting parsed entries/media for senders only; do not put translation, enrichment, route lookup, or subscription command fallback behavior into formatter code. Platform-neutral message ordering belongs in `MessageComponentSorter`; OneBot should keep media nodes before text/via nodes. AI filtering belongs in `ContentHandlerRuntime`.
- Shared cross-layer constants live in `src/shared/constants.py`; do not recreate `src/domain/constants.py`. Typed config/runtime models and config parsing live under `src/infrastructure/config/`, with data models in `datamodels.py` and AstrBot/raw-to-runtime loading in `config_loader.py`.

## Dev and test commands

```bash
python tests/run_tests.py -v
python tests/run_tests.py --category unit
python tests/run_tests.py --category integration
pytest tests/ -v
```

From AstrBot root:

```bash
uv run ruff format data/plugins/astrbot_plugin_rsshub
uv run ruff check data/plugins/astrbot_plugin_rsshub
```

## Current progress snapshot

Recently completed regression fixes include:

- Restored command signatures/semantics for `/sub_test`, `/sub`, `/unsub`, `/sub_list`, `/sub_export`, `/sub_import`.
- Restored real push behavior for `/sub_test`; chat command now sends the latest entry only.
- Restored compatibility formatting (`via ...`) and OneBot merged-forward naming path.
- Added regression tests for handlers/application behavior.
- Command surface slimming:
  - Removed chat command `/refresh`.
  - Removed chat command `/batch_unsub` (use `/unsub` batch).
  - Replaced `/sub_set` + `/sub_set_user` + `/sub_get_user` with command group `/sub_profile set|get`.
  - Session config commands switched to command group: `/sub_session set|get`.
- Push job control upgrades:
  - Added `/sub_status` for runtime queue visibility.
  - Upgraded `/sub_stop` to support no-arg/job_id/feed_id/all.
  - Cancelled push history now persists `status=stopped` (non-retry).
- Added `/rsshelp` image help command and generator pipeline:
  - `scripts/generate_rsshelp_image.py`
  - `assets/help/rsshelp_template.html`
  - `assets/help/rsshelp.png` (committed pre-generated image)
- Centralized runtime data/cache/export paths in `src/infrastructure/utils/paths.py` to avoid plugin-repo `data/` pollution during local debugging.
- Removed built-in content-processing pipeline:
  - `FeedPollingService` dispatches parsed/deduplicated entries without `ContentProcessingService`.
  - Plugin Pages exposes existing subscription management, user management, subscription defaults, refresh/test actions, push history, stats, and Routes KB entry points; it does not expose content pipeline settings or subscription import/export.
  - Traditional translation pipeline, translation cache model/UI/API, AI filter/enrich settings, RSSHub route stub LLM tools, and legacy `ContentFilterService` are removed. Future translation/summarization work belongs in AstrBot LLM or extension paths.
- Plugin Pages handler editing is schema-driven:
  - User and subscription editors share the same handler list editing model.
  - UI supports enable/disable, ordering, add built-in handler, delete, schema fields, and raw JSON advanced mode.
  - Frontend calls `/handlers/schema` when available and falls back to built-in AI handler schema.
  - `ai_transform(scope=xml)` rewrites full `raw_xml`, validates it via an internal tool, and reparses XML before normal dispatch formatting.
  - `link_preview` controls were removed from Plugin Pages.
- Simplified plugin user states to `用户` and `已封禁`; legacy non-negative states are treated as normal users and no plugin-owned admin/guest role should be reintroduced.
- Removed Plugin Pages `webadmin` fallback behavior; user-owned Web API writes now require explicit `user_id` and front-end actions pass the existing subscription owner.
- `sender_strategies.enabled_platforms` is rendered as a compact platform multi-select for `telegram` / `aiocqhttp` / `qq_official` and saves inside the `sender_strategies` object while still reading legacy bool-map configs.
- `_conf_schema.json` uses dropdowns for Routes KB source mode/source URLs and sliders for bounded numeric settings; Route KB raw URL joining preserves proxy prefixes such as `https://ghfast.top/https://raw...`.
- Added RSSHub Routes KB sync runtime:
  - Application service handles manifest diff, sha256 validation, single running sync task, and prompt-injection intent guard.
  - Infrastructure adapters support mirror/auto/github/local sources, fallback document fetch in auto mode, and AstrBot KB upload/delete by stable doc name.
  - `/rsshub_kb_init` can create an empty AstrBot KB using configured or default embedding/rerank providers.
  - The knowledgebase workflow consumes the independent `FlanChanXwO/rsshub-routes-knowledgebase` repository published at `main`.
  - Chat commands, Web API, and Plugin Pages expose init/sync/status/task; route lookup stays on AstrBot KB configuration/tooling and direct URL reasoning, not custom route-search/build LLM tools.
- Hardened media failure fallback and push history stability:
  - first-send history now persists `media_urls`, retry dispatch reuses them instead of dropping media on retry
  - OneBot merged-forward failure falls back to text-only Nodes in auto/classic style; original style uses parsed layout fragments instead of one large forward package
  - push history failure reasons and sender exception details are truncated to 512 chars, and repository reads truncate legacy dirty values before entity construction
  - `failed_queue_capacity=0` disables automatic retry pickup only; failed history retention and failure-facing audit remain intact
  - `failed_queue_max_retries` is the push history automatic retry ceiling; records beyond the limit remain visible as failed history
  - `deduplicate_multi_bot` only suppresses equivalent final payloads within the same `target_session`, and suppressed records persist as `skipped`
- Rebuilt subscription/user profile schema:
  - `rsshub_sub` and `rsshub_user` now include `handlers`
  - legacy `use_sub_config`, `use_user_config`, `translate`, and `translate_target_lang` columns are removed by migration/self-heal
  - profile inheritance is represented only by `-100`; user profile options default to `-100` to inherit global defaults
  - TOML import/export and Plugin Pages preserve editable handler chains
- Added agent XML instant-push path:
  - `rss_push_xml_entry` validates XML/HTML payloads, rejects malformed / oversized / DOCTYPE input, and parses tags into message content + media
  - agent pushes are tracked in `push_history` with `source_type=agent` and `source_key`, without exposing or depending on `sub_id`
  - agent deduplication uses success-only scope `(source_type, source_key, user_id, target_session, entry_guid)` and retries reuse history target/media directly
  - XML agent push history persists `raw_xml`, and `rss_list_push_history` exposes current-session JSON history without `sub_id`

## Update policy

When architecture, command surface, push formatting, config paths, or test/lint workflow changes, update both `CLAUDE.md` and `AGENTS.md` in the same change.
