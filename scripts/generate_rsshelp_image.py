#!/usr/bin/env python3
"""Generate rsshelp PNG from command decorators/docstrings in main.py.

Primary path:
- Parse `main.py` command methods and docstrings with AST.
- Render HTML via Jinja2 from scripts/template/ into a temp file.
- Screenshot with Playwright; fallback to Pillow if unavailable unless disabled.

Output:
- default: assets/help/rsshelp_light.png and assets/help/rsshelp_dark.png
Resources: scripts/resources/  (logo from RssHub.svg)
"""

from __future__ import annotations

import argparse
import ast
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from PIL import Image, ImageDraw, ImageFont

PLUGIN_ROOT = Path(__file__).resolve().parent.parent  # .../astrbot_plugin_rsshub/
MAIN_PY = PLUGIN_ROOT / "main.py"

# Template and resources under scripts/
SCRIPT_DIR = PLUGIN_ROOT / "scripts"
TEMPLATE_DIR = SCRIPT_DIR / "template"
TEMPLATE_NAME = "rsshelp_template.html"
RESOURCES_DIR = SCRIPT_DIR / "resources"
# Output goes into the same path used by /rsshelp at runtime.
OUTPUT_DIR = PLUGIN_ROOT / "assets" / "help"
THEME_OUTPUT_PNG = {
    "light": OUTPUT_DIR / "rsshelp_light.png",
    "dark": OUTPUT_DIR / "rsshelp_dark.png",
}

THEME_CSS = {
    "light": "light_theme.css",
    "dark": "dark_theme.css",
}


def _with_svg_classes(svg: str, classes: str) -> str:
    if " class=" in svg[:200]:
        return svg.replace(' class="', f' class="{classes} ', 1)
    return svg.replace("<svg ", f'<svg class="{classes}" ', 1)


@dataclass
class CommandDoc:
    command: str
    aliases: list[str]
    summary: str
    usage: list[str]
    examples: list[str]
    method_name: str
    type: str = "command"
    group_name: str = ""
    group_aliases: list[str] | None = None

    @property
    def display_command(self) -> str:
        if self.command.startswith("/"):
            return self.command
        return f"/{self.command}"

    @property
    def display_aliases(self) -> list[str]:
        aliases = list(self.aliases)
        for alias in self.group_aliases or []:
            if alias not in aliases:
                aliases.append(alias)
        return [alias if alias.startswith("/") else f"/{alias}" for alias in aliases]


def _extract_aliases(node: ast.Call) -> list[str]:
    for kw in node.keywords:
        if kw.arg == "alias" and isinstance(kw.value, ast.Set):
            return [
                elt.value
                for elt in kw.value.elts
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
            ]
    return []


def _extract_str_arg(node: ast.Call) -> str:
    if node.args and isinstance(node.args[0], ast.Constant):
        value = node.args[0].value
        if isinstance(value, str):
            return value
    return ""


def _doc_for_node(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> tuple[str, list[str], list[str]]:
    doc = ast.get_docstring(node) or ""
    lines = [line.strip() for line in doc.strip().splitlines()]
    summary = next((line for line in lines if line), node.name)
    usage: list[str] = []
    examples: list[str] = []
    section: str | None = None

    for line in lines[1:]:
        if not line:
            continue
        normalized = line.rstrip(":：")
        if normalized == "用法":
            section = "usage"
            continue
        if normalized == "示例":
            section = "examples"
            continue
        if section not in {"usage", "examples"}:
            continue

        value = line[2:].strip() if line.startswith("- ") else line
        if section == "usage":
            usage.append(value)
        else:
            examples.append(value)

    return summary, usage, examples


def _summary_for_node(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    return _doc_for_node(node)[0]


def parse_main_commands(main_py: Path) -> list[CommandDoc]:
    tree = ast.parse(main_py.read_text(encoding="utf-8"))
    cls = next(
        n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "RSSHubPlugin"
    )

    group_methods: dict[str, tuple[str, list[str], str, list[str], list[str]]] = {}
    for node in cls.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute):
                if dec.func.attr == "command_group":
                    group_name = _extract_str_arg(dec)
                    group_alias = _extract_aliases(dec)
                    if group_name:
                        summary, usage, examples = _doc_for_node(node)
                        group_methods[node.name] = (
                            group_name,
                            group_alias,
                            summary,
                            usage,
                            examples,
                        )

    docs: list[CommandDoc] = []
    for method_name, (
        group_name,
        group_aliases,
        summary,
        usage,
        examples,
    ) in group_methods.items():
        docs.append(
            CommandDoc(
                command=group_name,
                aliases=group_aliases,
                summary=summary,
                usage=usage,
                examples=examples,
                method_name=method_name,
                type="group",
                group_name=group_name,
            )
        )

    for node in cls.body:
        if not isinstance(node, ast.AsyncFunctionDef):
            continue

        summary, usage, examples = _doc_for_node(node)

        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call) or not isinstance(dec.func, ast.Attribute):
                continue
            if dec.func.attr != "command":
                continue

            # Only include root commands: @filter.command("...")
            base = dec.func.value
            if not isinstance(base, ast.Name) or base.id != "filter":
                continue

            cmd = _extract_str_arg(dec)
            aliases = _extract_aliases(dec)
            docs.append(
                CommandDoc(
                    command=cmd,
                    aliases=aliases,
                    summary=summary,
                    usage=usage,
                    examples=examples,
                    method_name=node.name,
                )
            )

        # parse group subcommand decorators: @group_method.command("set", ...)
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call) or not isinstance(dec.func, ast.Attribute):
                continue
            if dec.func.attr != "command":
                continue
            base = dec.func.value
            if not isinstance(base, ast.Name):
                continue
            group_meta = group_methods.get(base.id)
            if not group_meta:
                continue
            sub_cmd = _extract_str_arg(dec)
            aliases = _extract_aliases(dec)
            group_name, group_aliases, _group_summary, _group_usage, _group_examples = (
                group_meta
            )
            docs.append(
                CommandDoc(
                    command=f"{group_name} {sub_cmd}",
                    aliases=aliases,
                    summary=summary,
                    usage=usage,
                    examples=examples,
                    method_name=node.name,
                    type="group_command",
                    group_name=group_name,
                    group_aliases=group_aliases,
                )
            )

    # Remove duplicates
    uniq: dict[tuple[str, str], CommandDoc] = {}
    for d in docs:
        uniq[(d.method_name, d.command)] = d
    return list(uniq.values())


def _group_commands(cmds: list[CommandDoc]) -> list[dict]:
    groups = {
        "订阅管理": [],
        "配置命令": [],
        "管理员": [],
        "其他命令": [],
    }

    def sort_key(cmd: CommandDoc) -> tuple[str, int, str]:
        type_rank = {"command": 0, "group": 1, "group_command": 2}.get(cmd.type, 9)
        return (cmd.group_name or cmd.command, type_rank, cmd.command)

    for c in sorted(cmds, key=sort_key):
        if c.command.startswith("sub_profile") or c.command.startswith("sub_session"):
            groups["配置命令"].append(c)
        elif c.command.startswith("sub_test") or c.command.startswith("rsshub_kb_"):
            groups["管理员"].append(c)
        elif (
            c.command.startswith("sub_status")
            or c.command.startswith("sub_stop")
            or c.command.startswith("sub_export")
            or c.command.startswith("sub_import")
            or c.command.startswith("rsshelp")
        ):
            groups["其他命令"].append(c)
        else:
            groups["订阅管理"].append(c)
    return [{"title": k, "commands": v} for k, v in groups.items() if v]


def render_html_to_temp(commands: list[CommandDoc], theme: str = "light") -> Path:
    # Read external resources and inline them so temp file is self-contained
    css_file = TEMPLATE_DIR / THEME_CSS.get(theme, THEME_CSS["light"])
    css = css_file.read_text(encoding="utf-8")
    rsslogo_svg = _with_svg_classes(
        (RESOURCES_DIR / "RssHub.svg").read_text(encoding="utf-8"),
        "header-logo rsshub-logo",
    )

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template(TEMPLATE_NAME)
    grouped = _group_commands(commands)
    html = template.render(
        groups=grouped,
        total_commands=len(commands),
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        inline_css=css,
        rsslogo_svg=rsslogo_svg,
    )
    with tempfile.NamedTemporaryFile(
        suffix=".html", delete=False, mode="w", encoding="utf-8"
    ) as f:
        f.write(html)
        return Path(f.name)


def render_png_with_playwright(html_path: Path, output_png: Path) -> bool:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        print(f"playwright import failed: {exc}", file=sys.stderr)
        return False
    try:
        with sync_playwright() as p:
            output_png.parent.mkdir(parents=True, exist_ok=True)
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1040, "height": 600})
            page.goto(html_path.resolve().as_uri(), wait_until="networkidle")
            page.evaluate("() => document.fonts.ready")
            # Use card height + body padding to determine exact viewport height.
            # This avoids viewport-size-dependent scrollHeight bugs.
            height = page.evaluate(
                "document.querySelector('.card').getBoundingClientRect().bottom + "
                "parseFloat(getComputedStyle(document.documentElement).paddingTop) + "
                "parseFloat(getComputedStyle(document.body).paddingBottom)"
            )
            page.set_viewport_size({"width": 1040, "height": int(height) + 1})
            page.screenshot(path=str(output_png), full_page=True)
            browser.close()
        return True
    except Exception as exc:
        print(f"playwright render failed: {exc}", file=sys.stderr)
        return False
    finally:
        try:
            html_path.unlink(missing_ok=True)
        except Exception:
            pass


def render_theme(
    *,
    commands: list[CommandDoc],
    theme: str,
    output_png: Path,
    require_playwright: bool,
) -> None:
    html_path = render_html_to_temp(commands, theme=theme)

    ok = render_png_with_playwright(html_path, output_png)
    if not ok:
        if require_playwright:
            raise RuntimeError(
                "Playwright rendering failed. Install Chromium for the selected "
                "Python environment with: python -m playwright install chromium"
            )
        render_png_fallback(commands, output_png, theme=theme)

    print(f"generated {theme}: {output_png}")


def _font(size: int) -> ImageFont.ImageFont:
    for name in [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansSC-Regular.otf",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/truetype/arphic/uming.ttc",
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "C:/Windows/Fonts/simsun.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    ]:
        p = Path(name)
        if p.exists():
            try:
                return ImageFont.truetype(str(p), size=size)
            except Exception:
                continue
    return ImageFont.load_default()


def render_png_fallback(
    commands: list[CommandDoc], output_png: Path, theme: str = "light"
) -> None:
    width = 1040
    padding = 40
    line_h = 28

    if theme == "dark":
        bg_color = "#1b1b2e"
        card_bg = "#222236"
        card_outline = "#3a3040"
        text_primary = "#d8dce6"
        text_secondary = "#8898a8"
        text_muted = "#788898"
        accent = "#ff7a30"
        accent_light = "#ff8a40"
        group_cmd_color = "#e8956a"
        group_bg = "#2a2a3e"
        group_outline = "#3a3040"
        group_title_color = "#d8dce6"
        ellipse1 = "#252035"
        ellipse2 = "#2a2235"
        brand_bg = "#ff7a30"
        title_color = "#d8dce6"
    else:
        bg_color = "#fff7f3"
        card_bg = "#ffffff"
        card_outline = "#ffd8c2"
        text_primary = "#24313f"
        text_secondary = "#6f7f90"
        text_muted = "#6f7f90"
        accent = "#ff5d01"
        accent_light = "#ff5d01"
        group_cmd_color = "#9b3f08"
        group_bg = "#fffaf7"
        group_outline = "#ffe9db"
        group_title_color = "#24313f"
        ellipse1 = "#fff0e7"
        ellipse2 = "#ffe3d1"
        brand_bg = "#ff5d01"
        title_color = "#10243d"

    grouped = _group_commands(commands)
    row_heights: list[int] = []
    for g in grouped:
        h = 72
        for c in g["commands"]:
            detail_lines = len(c.usage) + len(c.examples)
            h += 64 + (24 if c.display_aliases else 0) + detail_lines * 20
        row_heights.append(h + 18)
    total_h = 150 + sum(row_heights) + 72
    total_h = max(total_h, 760)

    im = Image.new("RGB", (width, total_h), bg_color)
    draw = ImageDraw.Draw(im)
    font_brand = _font(18)
    font_title = _font(50)
    font_h2 = _font(30)
    font_cmd = _font(22)
    font_text = _font(18)
    font_meta = _font(16)

    draw.ellipse((1120, -40, 1420, 260), fill=ellipse1)
    draw.ellipse((1180, 20, 1500, 340), fill=ellipse2)
    draw.rectangle(
        (20, 20, width - 20, total_h - 20), fill=card_bg, outline=card_outline, width=2
    )
    draw.rounded_rectangle(
        (52, 54, 66, 68),
        radius=4,
        fill=brand_bg,
    )
    draw.text((78, 46), "RSSHub for AstrBot", font=font_brand, fill=accent)
    draw.text((50, 45), "RSSHub 命令帮助", font=font_title, fill=title_color)
    draw.text(
        (50, 108),
        "预生成静态帮助图，命令说明来自当前插件入口定义",
        font=font_text,
        fill=text_secondary,
    )
    draw.text(
        (50, 138),
        f"命令数：{len(commands)}",
        font=font_meta,
        fill=text_secondary,
    )

    y = 182
    box_w = width - padding * 2
    for idx, g in enumerate(grouped):
        x = padding
        box_y = y
        h = row_heights[idx]
        draw.rounded_rectangle(
            (x, box_y, x + box_w, box_y + h),
            radius=18,
            fill=group_bg,
            outline=group_outline,
            width=2,
        )
        draw.text(
            (x + 18, box_y + 16), g["title"], font=font_h2, fill=group_title_color
        )
        inner_y = box_y + 62
        for c in g["commands"]:
            prefix = "  " if c.type == "group_command" else ""
            suffix = (
                "  [命令组]"
                if c.type == "group"
                else "  [子命令]"
                if c.type == "group_command"
                else ""
            )
            draw.text(
                (x + 18, inner_y),
                f"{prefix}{c.display_command}{suffix}",
                font=font_cmd,
                fill=group_cmd_color if c.type == "group" else accent_light,
            )
            inner_y += line_h
            draw.text((x + 18, inner_y), c.summary, font=font_text, fill=text_primary)
            inner_y += line_h
            if c.display_aliases:
                alias_text = " / ".join(c.display_aliases)
                draw.text(
                    (x + 18, inner_y), alias_text, font=font_meta, fill=text_muted
                )
                inner_y += 24
            for label, lines in (("用法", c.usage), ("示例", c.examples)):
                if not lines:
                    continue
                draw.text(
                    (x + 18, inner_y),
                    f"{label}: {' / '.join(lines)}",
                    font=font_meta,
                    fill=text_muted,
                )
                inner_y += 20
        y += h + 16

    output_png.parent.mkdir(parents=True, exist_ok=True)
    im.save(output_png, format="PNG")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--main", default=str(MAIN_PY))
    parser.add_argument(
        "--output-png",
        default=None,
        help="Output path for single-theme generation. When omitted, the default run generates both themes.",
    )
    parser.add_argument(
        "--require-playwright",
        action="store_true",
        help="Fail instead of using the Pillow fallback when Playwright rendering is unavailable.",
    )
    parser.add_argument(
        "--theme",
        choices=["light", "dark"],
        default=None,
        help="Generate only one theme. If omitted with no --output-png, both light and dark are generated.",
    )
    args = parser.parse_args()

    main_py = Path(args.main)
    commands = parse_main_commands(main_py)

    if args.output_png is None and args.theme is None:
        for theme, output_png in THEME_OUTPUT_PNG.items():
            render_theme(
                commands=commands,
                theme=theme,
                output_png=output_png,
                require_playwright=args.require_playwright,
            )
        return 0

    theme = args.theme or "light"
    output_png = Path(args.output_png) if args.output_png else THEME_OUTPUT_PNG[theme]
    render_theme(
        commands=commands,
        theme=theme,
        output_png=output_png,
        require_playwright=args.require_playwright,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
