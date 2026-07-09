# AGENTS.md

This is `astrbot_plugin_rsshub`, an AstrBot plugin that turns RSSHub feeds into cross-platform bot pushes.

## Build, Test, and Lint

Useful checks from the AstrBot project root:

```bash
uv run ruff format data/plugins/astrbot_plugin_rsshub
uv run ruff check data/plugins/astrbot_plugin_rsshub
uv run python -m pytest data/plugins/astrbot_plugin_rsshub/tests/ -v
```

Fast checks from the plugin directory:

```bash
python tests/run_tests.py --category unit
python tests/run_tests.py --category integration
./tests/run_tests.sh --category unit
./tests/run_tests.sh --category integration
```

See `docs/dev/testing.md` for the regression matrix and when to run narrower suites.

## Project Layout

- `_conf_schema.json` - AstrBot plugin configuration schema shown in the host UI
- `metadata.yaml` - AstrBot plugin metadata
- `main.py` / `bootstrap.py` - AstrBot lifecycle entry and runtime composition
- `src/` - Python domain, application, infrastructure, and interface code
- `pages/` - Plugin Pages frontend
- `docs/` - project, usage, and maintenance documentation
- `tests/` - unit, integration, frontend, fixtures, and mocks
- `scripts/` - maintenance and diagnostic helpers

Read `docs/project/architecture.md` for detailed layer responsibilities and data flow.

## Where to Look

- Maintenance rules: `docs/dev/maintenance.md`
- Configuration and domain semantics: `docs/project/domain-model.md`
- Commands, AI tools, user settings, push history: `docs/project/application.md`
- Platforms, media, cache, proxies: `docs/project/platforms.md`
- Web API and Plugin Pages: `docs/project/web_api.md`
