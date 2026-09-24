"""SVG and raster renderers for public architecture previews."""

from __future__ import annotations

from html import escape
from io import BytesIO
from math import hypot
from pathlib import Path
from typing import Any, Iterator, NamedTuple

from PIL import Image, ImageDraw, ImageFont


CARD_WIDTH = 320
CARD_HEIGHT = 200
PADDING = 72
HEADER_HEIGHT = 140
MIN_WIDTH = 960
MIN_HEIGHT = 520
MAX_WIDTH = 3200
MAX_HEIGHT = 1900

# These values intentionally mirror the editor's dark canvas rather than the
# old generic navy preview. The preview is a product surface in its own right:
# it should feel like a Diagramwise artifact even when shown outside the app.
CANVAS = "#0f1012"
CANVAS_GRID = "#1b1d21"
SURFACE = "#17191d"
BORDER = "#30343b"
TEXT = "#f5f5f3"
MUTED = "#a9adb5"
EDGE = "#b8bec8"
LABEL_SURFACE = "#252932"
LABEL_BORDER = "#4b5360"
BRAND = "#d94683"


class PreviewGeometry(NamedTuple):
    by_id: dict[str, dict[str, Any]]
    positions: dict[str, tuple[float, float]]
    width: int
    height: int


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Use a real sans font when the runtime provides one, with a safe fallback."""

    names = (
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
        "Arial Bold.ttf" if bold else "Arial.ttf",
    )
    paths = [
        Path("/usr/share/fonts/truetype/dejavu") / name for name in names
    ] + [Path("C:/Windows/Fonts") / name for name in names]
    for path in paths:
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size=size)
            except OSError:
                pass
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow versions before the scalable default font.
        return ImageFont.load_default()


def _text(value: Any, fallback: str = "") -> str:
    return escape(str(value or fallback).strip())


def _wrap(value: str, limit: int = 34) -> list[str]:
    words = value.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and len(candidate) > limit:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines[:3]


def _build_preview_geometry(nodes: list[Any]) -> PreviewGeometry:
    by_id = {
        str(node.get("id")): node
        for node in nodes
        if isinstance(node, dict) and node.get("id") is not None
    }
    raw_positions: dict[str, tuple[float, float]] = {}
    for node_id, node in by_id.items():
        position = node.get("position") or {}
        raw_positions[node_id] = (
            float(position.get("x", 0) or 0),
            float(position.get("y", 0) or 0),
        )

    min_x = min((position[0] for position in raw_positions.values()), default=0)
    min_y = min((position[1] for position in raw_positions.values()), default=0)
    positions: dict[str, tuple[float, float]] = {}
    max_right = 0.0
    max_bottom = 0.0
    for node_id, (raw_x, raw_y) in raw_positions.items():
        x = raw_x - min_x + PADDING
        y = raw_y - min_y + HEADER_HEIGHT
        positions[node_id] = (x, y)
        max_right = max(max_right, x + CARD_WIDTH)
        max_bottom = max(max_bottom, y + CARD_HEIGHT)
    return PreviewGeometry(
        by_id=by_id,
        positions=positions,
        width=max(MIN_WIDTH, min(MAX_WIDTH, int(max_right + PADDING))),
        height=max(MIN_HEIGHT, min(MAX_HEIGHT, int(max_bottom + PADDING))),
    )


def _node_data(node: dict[str, Any]) -> dict[str, Any]:
    value = node.get("data")
    return value if isinstance(value, dict) else {}


def _node_label(node: dict[str, Any], node_id: str) -> str:
    data = _node_data(node)
    return str(data.get("componentName") or data.get("label") or node_id).strip()


def _node_subtitle(node: dict[str, Any]) -> str:
    data = _node_data(node)
    return str(data.get("subtitle") or data.get("description") or "").strip()


def _node_theme(node: dict[str, Any]) -> tuple[str, str, str]:
    """Return accent, badge background, and semantic icon kind."""

    data = _node_data(node)
    provider = str(data.get("provider") or data.get("catalogRef") or "").lower()
    category = str(data.get("category") or "").lower()
    ref = str(data.get("componentId") or data.get("catalogRef") or "").lower()

    if "aws" in provider or ref.startswith("aws-"):
        return "#f59e0b", "#3a2a12", category or "cloud"
    if "azure" in provider or ref.startswith("azure-"):
        return "#38bdf8", "#102f3d", category or "cloud"
    if "gcp" in provider or ref.startswith("gcp-"):
        return "#60a5fa", "#172f50", category or "cloud"
    if "kubernetes" in provider or ref.startswith("k8s"):
        return "#4f8fe8", "#152b4d", category or "compute"
    if category in {"database", "data", "data layer"} or "database" in ref or "postgres" in ref:
        return "#8b5cf6", "#2b1c4b", "database"
    if category == "cache" or "redis" in ref or "cache" in ref:
        return "#ef5da8", "#4a1e39", "cache"
    if category in {"storage", "object storage"} or "storage" in ref or "s3" in ref:
        return "#e879f9", "#431b4c", "storage"
    if category in {"network", "delivery", "cdn", "frontend"} or "cdn" in ref or "cloudfront" in ref:
        return "#22d3ee", "#103b45", "network"
    if category in {"messaging", "queue", "stream"} or "queue" in ref or "topic" in ref:
        return "#34d399", "#123d31", "queue"
    if category in {"compute", "services", "service"} or "service" in ref or "server" in ref:
        return "#a78bfa", "#2b2250", "compute"
    return BRAND, "#451d36", "custom"


def _anchor(
    position: tuple[float, float],
    handle: Any,
    fallback: str,
) -> tuple[float, float, str]:
    normalized = str(handle or fallback).split(":")[-1].lower()
    side = next(
        (candidate for candidate in ("top", "right", "bottom", "left") if normalized.startswith(candidate)),
        fallback,
    )
    fraction = 0.5
    if normalized.endswith("-top") or normalized.endswith("-left"):
        fraction = 0.25
    elif normalized.endswith("-bottom") or normalized.endswith("-right"):
        fraction = 0.75
    x, y = position
    if side in {"top", "bottom"}:
        return x + CARD_WIDTH * fraction, y if side == "top" else y + CARD_HEIGHT, side
    return x if side == "left" else x + CARD_WIDTH, y + CARD_HEIGHT * fraction, side


def _edge_points(
    edge: dict[str, Any],
    positions: dict[str, tuple[float, float]],
) -> list[tuple[float, float]] | None:
    source_id = str(edge.get("source"))
    target_id = str(edge.get("target"))
    source_position = positions.get(source_id)
    target_position = positions.get(target_id)
    if not source_position or not target_position:
        return None

    data = edge.get("data") or {}
    source_x, source_y = source_position
    target_x, target_y = target_position
    forward = target_x >= source_x
    source_fallback = "right" if forward else "left"
    target_fallback = "left" if forward else "right"
    source = _anchor(source_position, edge.get("sourceHandle"), source_fallback)
    target = _anchor(target_position, edge.get("targetHandle"), target_fallback)
    routing_kind = str(data.get("routingKind") or "forward")

    if source[2] in {"top", "bottom"} or target[2] in {"top", "bottom"}:
        side = "top" if source[2] == "top" or target[2] == "top" else "bottom"
        lane = min(source_y, target_y) - 34 if side == "top" else max(source_y + CARD_HEIGHT, target_y + CARD_HEIGHT) + 34
        return [source[:2], (source[0], lane), (target[0], lane), target[:2]]

    if routing_kind in {"cycle", "backward"} or not forward:
        lane = min(source_y, target_y) - 34 if source_y <= target_y else max(source_y + CARD_HEIGHT, target_y + CARD_HEIGHT) + 34
        bend = 32 if forward else -32
        return [source[:2], (source[0] + bend, source[1]), (source[0] + bend, lane), (target[0] - bend, lane), (target[0] - bend, target[1]), target[:2]]

    mid_x = (source[0] + target[0]) / 2
    return [source[:2], (mid_x, source[1]), (mid_x, target[1]), target[:2]]


def _polyline_label_point(points: list[tuple[float, float]]) -> tuple[float, float, float, float]:
    segments = list(zip(points, points[1:]))
    source, target = max(
        segments,
        key=lambda pair: hypot(pair[1][0] - pair[0][0], pair[1][1] - pair[0][1]),
    )
    return (
        (source[0] + target[0]) / 2,
        (source[1] + target[1]) / 2,
        target[0] - source[0],
        target[1] - source[1],
    )


def _fit_lines(text: str, *, max_chars: int = 34, max_lines: int = 3) -> list[str]:
    return _wrap(text, max_chars)[:max_lines]


def _draw_category_icon(
    draw: ImageDraw.ImageDraw,
    center: tuple[float, float],
    kind: str,
    accent: str,
) -> None:
    """Draw a small consistent vector icon instead of a placeholder glyph."""

    cx, cy = center
    line = accent
    dark = "#101114"
    if kind in {"database", "cache"}:
        draw.ellipse((cx - 17, cy - 14, cx + 17, cy - 3), outline=line, width=2)
        draw.line((cx - 17, cy - 9, cx - 17, cy + 14), fill=line, width=2)
        draw.line((cx + 17, cy - 9, cx + 17, cy + 14), fill=line, width=2)
        draw.arc((cx - 17, cy + 7, cx + 17, cy + 19), 0, 180, fill=line, width=2)
        if kind == "cache":
            draw.line((cx - 8, cy + 1, cx + 8, cy + 1), fill=dark, width=2)
    elif kind == "storage":
        draw.rounded_rectangle((cx - 17, cy - 12, cx + 17, cy + 15), radius=5, outline=line, width=2)
        draw.arc((cx - 17, cy - 17, cx + 17, cy - 5), 180, 360, fill=line, width=2)
        draw.line((cx - 12, cy + 6, cx + 12, cy + 6), fill=line, width=2)
    elif kind == "network":
        draw.ellipse((cx - 17, cy - 17, cx + 17, cy + 17), outline=line, width=2)
        draw.arc((cx - 9, cy - 17, cx + 9, cy + 17), 90, 270, fill=line, width=2)
        draw.line((cx - 17, cy, cx + 17, cy), fill=line, width=2)
    elif kind == "queue":
        draw.rounded_rectangle((cx - 16, cy - 12, cx + 16, cy - 1), radius=3, outline=line, width=2)
        draw.rounded_rectangle((cx - 16, cy + 5, cx + 16, cy + 16), radius=3, outline=line, width=2)
        draw.line((cx - 7, cy - 6, cx + 7, cy - 6), fill=line, width=2)
    elif kind in {"compute", "cloud"}:
        draw.rounded_rectangle((cx - 18, cy - 14, cx + 18, cy + 14), radius=5, outline=line, width=2)
        draw.line((cx - 10, cy - 5, cx + 10, cy - 5), fill=line, width=2)
        draw.line((cx - 10, cy + 4, cx + 6, cy + 4), fill=line, width=2)
        draw.ellipse((cx + 8, cy + 1, cx + 12, cy + 5), fill=line)
    else:
        draw.line((cx - 12, cy, cx, cy - 12), fill=line, width=2)
        draw.line((cx, cy - 12, cx + 13, cy + 4), fill=line, width=2)
        draw.line((cx - 12, cy, cx + 13, cy + 4), fill=line, width=2)
        for x, y in ((cx - 17, cy - 5), (cx - 5, cy - 18), (cx + 8, cy - 1)):
            draw.ellipse((x - 5, y - 5, x + 5, y + 5), outline=line, width=2)


def _edge_layouts(
    edges: list[Any], positions: dict[str, tuple[float, float]]
) -> Iterator[tuple[dict[str, Any], float, float, float, float, float]]:
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        source = positions.get(str(edge.get("source")))
        target = positions.get(str(edge.get("target")))
        if not source or not target:
            continue
        sx = source[0] + CARD_WIDTH
        sy_mid = source[1] + CARD_HEIGHT / 2
        tx, ty = target[0], target[1] + CARD_HEIGHT / 2
        if tx < sx:
            sx, tx = source[0], target[0] + CARD_WIDTH
        yield edge, sx, sy_mid, tx, ty, (sx + tx) / 2


def render_architecture_svg(
    *, title: str,
    nodes: list[Any],
    edges: list[Any],
) -> str:
    """Render a readable, public-safe preview from persisted canvas data.

    This intentionally renders labels and routing relationships only. It does
    not include private user metadata or depend on a browser/React runtime.
    """

    geometry = _build_preview_geometry(nodes)
    by_id = geometry.by_id
    positions = geometry.positions
    width = geometry.width
    height = geometry.height
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="{width}" height="{height}" role="img" aria-label="{_text(title, "Diagramwise architecture preview")}">',
        '<defs><marker id="arrow" markerWidth="9" markerHeight="9" refX="8" refY="4.5" orient="auto">'
        '<path d="M0,0 L9,4.5 L0,9 z" fill="#6b7280"/></marker></defs>',
        '<rect width="100%" height="100%" rx="24" fill="#111827"/>',
        f'<text x="{PADDING}" y="38" fill="#f9fafb" font-family="Inter,Arial,sans-serif" '
        f'font-size="20" font-weight="700">{_text(title, "Diagramwise architecture")}</text>',
    ]

    for edge, sx, sy_mid, tx, ty, midpoint in _edge_layouts(edges, positions):
        label = _text((edge.get("data") or {}).get("label") or edge.get("label"))
        parts.append(
            f'<path d="M {sx:.1f} {sy_mid:.1f} C {midpoint:.1f} {sy_mid:.1f}, '
            f'{midpoint:.1f} {ty:.1f}, {tx:.1f} {ty:.1f}" fill="none" '
            'stroke="#9ca3af" stroke-width="2" marker-end="url(#arrow)"/>'
        )
        if label:
            parts.append(
                f'<text x="{midpoint:.1f}" y="{(sy_mid + ty) / 2 - 8:.1f}" '
                'text-anchor="middle" fill="#d1d5db" font-family="Inter,Arial,sans-serif" '
                f'font-size="12">{label}</text>'
            )

    for node_id, node in by_id.items():
        x, y = positions[node_id]
        data = node.get("data") or {}
        label = _text(data.get("label") or node.get("label") or node_id)
        subtitle = _text(data.get("subtitle") or data.get("description"))
        parts.extend(
            [
                f'<rect x="{x:.1f}" y="{y:.1f}" width="{CARD_WIDTH}" height="{CARD_HEIGHT}" '
                'rx="14" fill="#1f2937" stroke="#4b5563" stroke-width="1.5"/>',
                f'<circle cx="{x + 34}" cy="{y + 36}" r="14" fill="#374151"/>',
                f'<circle cx="{x + 34}" cy="{y + 36}" r="4" fill="#f9fafb"/>',
                f'<text x="{x + 60}" y="{y + 42}" fill="#f9fafb" '
                'font-family="Inter,Arial,sans-serif" font-size="18" font-weight="700">'
                f'{label}</text>',
            ]
        )
        if subtitle:
            for index, line in enumerate(_wrap(subtitle)):
                parts.append(
                    f'<text x="{x + 24}" y="{y + 86 + index * 20}" fill="#d1d5db" '
                    'font-family="Inter,Arial,sans-serif" font-size="13">'
                    f'{line}</text>'
                )

    parts.append("</svg>")
    return "".join(parts)


def _draw_png_grid(draw: ImageDraw.ImageDraw, width: int, height: int) -> None:
    for x in range(24, width, 32):
        for y in range(24, height, 32):
            draw.ellipse((x, y, x + 2, y + 2), fill=CANVAS_GRID)


def _draw_png_brand_header(
    draw: ImageDraw.ImageDraw,
    *,
    title: str,
    description: str,
    title_font: Any,
    body_font: Any,
    small_font: Any,
) -> None:
    # Diagramwise mark: three connected nodes in the same visual family as the
    # product mark, drawn as geometry so the renderer has no asset dependency.
    draw.rounded_rectangle((PADDING, 26, PADDING + 34, 60), radius=10, fill="#291522", outline=BRAND, width=1)
    draw.line((PADDING + 11, 43, PADDING + 21, 35, PADDING + 25, 49), fill=BRAND, width=2)
    for x, y in ((PADDING + 10, 43), (PADDING + 22, 35), (PADDING + 26, 50)):
        draw.ellipse((x - 3, y - 3, x + 3, y + 3), fill=BRAND)
    draw.text((PADDING + 48, 31), "Diagramwise", fill=TEXT, font=small_font)
    draw.text((PADDING, 72), title or "Architecture preview", fill=TEXT, font=title_font)
    if description:
        for index, line in enumerate(_fit_lines(description, max_chars=96, max_lines=2)):
            draw.text((PADDING, 106 + index * 17), line, fill=MUTED, font=body_font)


def _draw_png_edges(
    draw: ImageDraw.ImageDraw,
    edges: list[Any],
    positions: dict[str, tuple[float, float]],
    label_font: Any,
    *,
    draw_labels: bool = False,
) -> None:
    occupied: list[tuple[float, float, float, float]] = []
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        points = _edge_points(edge, positions)
        if not points:
            continue
        data = edge.get("data") or {}
        if not draw_labels:
            draw.line(points, fill=EDGE, width=2, joint="curve")
            previous = points[-2]
            target = points[-1]
            dx = target[0] - previous[0]
            dy = target[1] - previous[1]
            length = max(hypot(dx, dy), 1)
            ux, uy = dx / length, dy / length
            px, py = -uy, ux
            arrow_size = 9
            base = (target[0] - ux * arrow_size, target[1] - uy * arrow_size)
            draw.polygon(
                [
                    target,
                    (base[0] + px * arrow_size * 0.55, base[1] + py * arrow_size * 0.55),
                    (base[0] - px * arrow_size * 0.55, base[1] - py * arrow_size * 0.55),
                ],
                fill=EDGE,
            )

        if not draw_labels:
            continue
        label = str(data.get("label") or edge.get("label") or "").strip()
        if not label:
            continue
        x, y, dx, dy = _polyline_label_point(points)
        length = max(hypot(dx, dy), 1)
        nx, ny = -dy / length, dx / length
        offset = 16 + min(max(float(data.get("labelOffset") or 0) * 28, 0), 22)
        lines = _fit_lines(label, max_chars=28, max_lines=2)
        max_width = max((draw.textbbox((0, 0), line, font=label_font)[2] for line in lines), default=0)
        label_width = max(74, min(230, max_width + 24))
        label_height = 18 + len(lines) * 15
        outside_offset = CARD_HEIGHT / 2 + label_height / 2 + 16
        candidates = [
            (x + nx * offset, y + ny * offset),
            (x - nx * offset, y - ny * offset),
            (x + nx * outside_offset, y + ny * outside_offset),
            (x - nx * outside_offset, y - ny * outside_offset),
        ]
        chosen = candidates[0]
        for candidate in candidates:
            rect = (
                candidate[0] - label_width / 2,
                candidate[1] - label_height / 2,
                candidate[0] + label_width / 2,
                candidate[1] + label_height / 2,
            )
            overlaps_node = any(
                rect[0] < node_x + CARD_WIDTH + 12
                and rect[2] > node_x - 12
                and rect[1] < node_y + CARD_HEIGHT + 12
                and rect[3] > node_y - 12
                for node_x, node_y in positions.values()
            )
            if not overlaps_node and not any(
                rect[0] < other[2] and rect[2] > other[0] and rect[1] < other[3] and rect[3] > other[1]
                for other in occupied
            ):
                chosen = candidate
                occupied.append(rect)
                break
        left = chosen[0] - label_width / 2
        top = chosen[1] - label_height / 2
        draw.rounded_rectangle(
            (left, top, left + label_width, top + label_height),
            radius=7,
            fill=LABEL_SURFACE,
            outline=LABEL_BORDER,
            width=1,
        )
        for index, line in enumerate(lines):
            draw.text(
                (chosen[0], top + 8 + index * 15),
                line,
                fill=TEXT,
                font=label_font,
                anchor="ma",
            )


def _draw_png_nodes(
    draw: ImageDraw.ImageDraw,
    by_id: dict[str, dict[str, Any]],
    positions: dict[str, tuple[float, float]],
    title_font: Any,
    subtitle_font: Any,
) -> None:
    for node_id, node in by_id.items():
        x, y = positions[node_id]
        label = _node_label(node, node_id)
        subtitle = _node_subtitle(node)
        accent, badge_background, icon_kind = _node_theme(node)
        draw.rounded_rectangle(
            (x, y, x + CARD_WIDTH, y + CARD_HEIGHT),
            radius=14,
            fill=SURFACE,
            outline=BORDER,
            width=1,
        )
        draw.line((x + 16, y + 1, x + CARD_WIDTH - 16, y + 1), fill=accent, width=1)
        draw.rounded_rectangle(
            (x + CARD_WIDTH / 2 - 30, y + 22, x + CARD_WIDTH / 2 + 30, y + 82),
            radius=15,
            fill=badge_background,
            outline=accent,
            width=1,
        )
        _draw_category_icon(draw, (x + CARD_WIDTH / 2, y + 52), icon_kind, accent)

        title_lines = _fit_lines(label, max_chars=28, max_lines=2)
        title_y = y + 104 - (len(title_lines) - 1) * 9
        for index, line in enumerate(title_lines):
            draw.text(
                (x + CARD_WIDTH / 2, title_y + index * 20),
                line,
                fill=TEXT,
                font=title_font,
                anchor="ma",
            )
        for index, line in enumerate(_fit_lines(subtitle, max_chars=42, max_lines=3)):
            draw.text(
                (x + CARD_WIDTH / 2, y + 143 + index * 17),
                line,
                fill=MUTED,
                font=subtitle_font,
                anchor="ma",
            )


def render_architecture_png(
    *,
    title: str,
    nodes: list[Any],
    edges: list[Any],
    description: str = "",
) -> bytes:
    """Render a raster preview for hosts that do not accept SVG tool images.

    Keep this path intentionally independent from browser rendering so MCP
    responses remain available in serverless environments.
    """

    geometry = _build_preview_geometry(nodes)
    image = Image.new("RGB", (geometry.width, geometry.height), CANVAS)
    draw = ImageDraw.Draw(image)
    _draw_png_grid(draw, geometry.width, geometry.height)
    _draw_png_brand_header(
        draw,
        title=str(title or "Diagramwise architecture"),
        description=str(description or ""),
        title_font=_font(23, bold=True),
        body_font=_font(13),
        small_font=_font(14, bold=True),
    )
    _draw_png_edges(
        draw,
        edges,
        geometry.positions,
        _font(12, bold=True),
    )
    _draw_png_nodes(
        draw,
        geometry.by_id,
        geometry.positions,
        _font(16, bold=True),
        _font(13),
    )
    _draw_png_edges(
        draw,
        edges,
        geometry.positions,
        _font(12, bold=True),
        draw_labels=True,
    )

    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()
