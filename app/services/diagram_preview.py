"""SVG and raster renderers for public architecture previews."""

from __future__ import annotations

from io import BytesIO
from html import escape
from typing import Any, Iterator, NamedTuple

from PIL import Image, ImageDraw, ImageFont


CARD_WIDTH = 320
CARD_HEIGHT = 200
PADDING = 64


class PreviewGeometry(NamedTuple):
    by_id: dict[str, dict[str, Any]]
    positions: dict[str, tuple[float, float]]
    width: int
    height: int


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
    positions: dict[str, tuple[float, float]] = {}
    max_right = 0.0
    max_bottom = 0.0
    for node_id, node in by_id.items():
        position = node.get("position") or {}
        x = float(position.get("x", 0) or 0) + PADDING
        y = float(position.get("y", 0) or 0) + PADDING
        positions[node_id] = (x, y)
        max_right = max(max_right, x + CARD_WIDTH)
        max_bottom = max(max_bottom, y + CARD_HEIGHT)
    return PreviewGeometry(
        by_id=by_id,
        positions=positions,
        width=max(800, min(2400, int(max_right + PADDING))),
        height=max(420, min(1600, int(max_bottom + PADDING))),
    )


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


def _draw_png_edges(draw: ImageDraw.ImageDraw, edges: list[Any], positions: dict[str, tuple[float, float]], font: Any) -> None:
    for edge, sx, sy_mid, tx, ty, midpoint in _edge_layouts(edges, positions):
        draw.line((sx, sy_mid, midpoint, sy_mid, midpoint, ty, tx, ty), fill="#9ca3af", width=2)
        arrow_size = 8
        draw.polygon(
            [(tx, ty), (tx - arrow_size, ty - arrow_size / 2), (tx - arrow_size, ty + arrow_size / 2)],
            fill="#9ca3af",
        )
        label = str((edge.get("data") or {}).get("label") or edge.get("label") or "").strip()
        if label:
            draw.text((midpoint, (sy_mid + ty) / 2 - 8), label, fill="#d1d5db", font=font, anchor="mm")


def _draw_png_nodes(
    draw: ImageDraw.ImageDraw,
    by_id: dict[str, dict[str, Any]],
    positions: dict[str, tuple[float, float]],
    font: Any,
    subtitle_font: Any,
) -> None:
    for node_id, node in by_id.items():
        x, y = positions[node_id]
        data = node.get("data") or {}
        label = str(data.get("label") or node.get("label") or node_id)
        subtitle = str(data.get("subtitle") or data.get("description") or "")
        draw.rounded_rectangle(
            (x, y, x + CARD_WIDTH, y + CARD_HEIGHT),
            radius=14,
            fill="#1f2937",
            outline="#4b5563",
            width=2,
        )
        draw.ellipse((x + 20, y + 22, x + 48, y + 50), fill="#374151")
        draw.ellipse((x + 30, y + 32, x + 38, y + 40), fill="#f9fafb")
        draw.text((x + 60, y + 28), label, fill="#f9fafb", font=font)
        for index, line in enumerate(_wrap(subtitle)):
            draw.text((x + 24, y + 74 + index * 20), line, fill="#d1d5db", font=subtitle_font)


def render_architecture_png(
    *,
    title: str,
    nodes: list[Any],
    edges: list[Any],
) -> bytes:
    """Render a raster preview for hosts that do not accept SVG tool images.

    Keep this path intentionally independent from browser rendering so MCP
    responses remain available in serverless environments.
    """

    geometry = _build_preview_geometry(nodes)
    image = Image.new("RGB", (geometry.width, geometry.height), "#111827")
    draw = ImageDraw.Draw(image)
    title_font = ImageFont.load_default(size=20)
    label_font = ImageFont.load_default(size=12)
    node_font = ImageFont.load_default(size=16)
    subtitle_font = ImageFont.load_default(size=13)

    draw.text((PADDING, 18), str(title or "Diagramwise architecture"), fill="#f9fafb", font=title_font)
    _draw_png_edges(draw, edges, geometry.positions, label_font)
    _draw_png_nodes(draw, geometry.by_id, geometry.positions, node_font, subtitle_font)

    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()
