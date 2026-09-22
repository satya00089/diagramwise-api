"""Small dependency-free SVG renderer for public architecture previews."""

from __future__ import annotations

from html import escape
from typing import Any


CARD_WIDTH = 320
CARD_HEIGHT = 200
PADDING = 64


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


def render_architecture_svg(
    *, title: str,
    nodes: list[Any],
    edges: list[Any],
) -> str:
    """Render a readable, public-safe preview from persisted canvas data.

    This intentionally renders labels and routing relationships only. It does
    not include private user metadata or depend on a browser/React runtime.
    """

    normalized_nodes = [node for node in nodes if isinstance(node, dict)]
    by_id: dict[str, dict[str, Any]] = {
        str(node.get("id")): node for node in normalized_nodes if node.get("id") is not None
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

    width = max(800, min(2400, int(max_right + PADDING)))
    height = max(420, min(1600, int(max_bottom + PADDING)))
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="{width}" height="{height}" role="img" aria-label="{_text(title, "Diagramwise architecture preview")}">',
        '<defs><marker id="arrow" markerWidth="9" markerHeight="9" refX="8" refY="4.5" orient="auto">'
        '<path d="M0,0 L9,4.5 L0,9 z" fill="#6b7280"/></marker></defs>',
        '<rect width="100%" height="100%" rx="24" fill="#111827"/>',
        f'<text x="{PADDING}" y="38" fill="#f9fafb" font-family="Inter,Arial,sans-serif" '
        f'font-size="20" font-weight="700">{_text(title, "Diagramwise architecture")}</text>',
    ]

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
        midpoint = (sx + tx) / 2
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
