from __future__ import annotations

import io
import json
import math
from pathlib import Path

from .models import VisualGraph
from .renderer import render_html, render_svg


_FORMATS = {'html', 'svg', 'json', 'png', 'webp', 'pdf'}
_COLORS = {
    'frontend': '#2196f3', 'backend': '#2dd4bf', 'database': '#8b5cf6', 'security': '#ec4899',
    'agent': '#f59e0b', 'tool': '#0ea5e9', 'cloud': '#34d399', 'external': '#22d3ee',
    'api': '#38bdf8', 'symbol': '#64748b', 'group': '#6366f1', 'project': '#2563eb', 'component': '#4f7cac',
}


def supported_export_formats() -> list[str]:
    return sorted(_FORMATS)


def _bounds(graph: VisualGraph):
    positioned = [node for node in graph.nodes if node.x is not None and node.y is not None]
    if not positioned:
        return 0.0, 0.0, 1200.0, 800.0
    left = min(float(node.x) for node in positioned) - 80
    top = min(float(node.y) for node in positioned) - 80
    right = max(float(node.x) + float(node.width) for node in positioned) + 80
    bottom = max(float(node.y) + float(node.height) for node in positioned) + 80
    return left, top, max(left + 320, right), max(top + 240, bottom)


def _raster(graph: VisualGraph, fmt: str) -> bytes:
    from PIL import Image, ImageDraw, ImageFont

    left, top, right, bottom = _bounds(graph)
    width, height = right - left, bottom - top
    scale = min(2.0, 3600.0 / max(width, 1), 2400.0 / max(height, 1))
    scale = max(0.45, scale)
    out_w, out_h = max(320, int(width * scale)), max(240, int(height * scale))
    image = Image.new('RGB', (out_w, out_h), '#030711')
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    node_map = {node.id: node for node in graph.nodes}

    def point(x, y):
        return ((float(x) - left) * scale, (float(y) - top) * scale)

    for edge in graph.edges:
        source, target = node_map.get(edge.source), node_map.get(edge.target)
        if not source or not target or source.x is None or target.x is None or source.y is None or target.y is None:
            continue
        a = point(source.x + source.width / 2, source.y + source.height / 2)
        b = point(target.x + target.width / 2, target.y + target.height / 2)
        draw.line([a, b], fill='#506784', width=max(1, int(2 * scale)))
        if edge.directed:
            angle = math.atan2(b[1] - a[1], b[0] - a[0])
            length = max(6, 9 * scale)
            wing = 0.55
            p1 = (b[0] - length * math.cos(angle - wing), b[1] - length * math.sin(angle - wing))
            p2 = (b[0] - length * math.cos(angle + wing), b[1] - length * math.sin(angle + wing))
            draw.polygon([b, p1, p2], fill='#506784')

    for node in graph.nodes:
        if node.x is None or node.y is None:
            continue
        x1, y1 = point(node.x, node.y)
        x2, y2 = point(node.x + node.width, node.y + node.height)
        stroke = _COLORS.get(node.category, _COLORS['component'])
        draw.rounded_rectangle([x1, y1, x2, y2], radius=max(4, int(9 * scale)), fill='#081522', outline=stroke, width=max(1, int(2 * scale)))
        if node.metadata.get('highlight'):
            inset = max(3, int(4 * scale))
            draw.rounded_rectangle([x1 - inset, y1 - inset, x2 + inset, y2 + inset], radius=max(5, int(12 * scale)), outline='#4de9ff', width=max(1, int(2 * scale)))
        label = node.label[:42]
        box = draw.textbbox((0, 0), label, font=font)
        tw, th = box[2] - box[0], box[3] - box[1]
        draw.text(((x1 + x2 - tw) / 2, (y1 + y2 - th) / 2), label, font=font, fill='#f3f7ff')

    output = io.BytesIO()
    if fmt == 'png':
        image.save(output, format='PNG', optimize=True)
    else:
        image.save(output, format='WEBP', quality=92, method=6)
    return output.getvalue()


def _pdf(graph: VisualGraph) -> bytes:
    from reportlab.pdfgen import canvas
    from reportlab.lib.colors import HexColor

    left, top, right, bottom = _bounds(graph)
    width, height = max(420.0, right - left), max(300.0, bottom - top)
    max_page = 14400.0
    scale = min(1.0, max_page / width, max_page / height)
    page_w, page_h = width * scale, height * scale
    output = io.BytesIO()
    c = canvas.Canvas(output, pagesize=(page_w, page_h))
    c.setFillColor(HexColor('#030711')); c.rect(0, 0, page_w, page_h, stroke=0, fill=1)
    node_map = {node.id: node for node in graph.nodes}

    def xy(x, y):
        return ((float(x) - left) * scale, page_h - (float(y) - top) * scale)

    c.setStrokeColor(HexColor('#506784')); c.setLineWidth(max(0.8, 1.4 * scale))
    for edge in graph.edges:
        a, b = node_map.get(edge.source), node_map.get(edge.target)
        if not a or not b or a.x is None or a.y is None or b.x is None or b.y is None:
            continue
        ax, ay = xy(a.x + a.width / 2, a.y + a.height / 2); bx, by = xy(b.x + b.width / 2, b.y + b.height / 2)
        c.line(ax, ay, bx, by)

    for node in graph.nodes:
        if node.x is None or node.y is None:
            continue
        x, y_top = xy(node.x, node.y); w, h = node.width * scale, node.height * scale; y = y_top - h
        c.setFillColor(HexColor('#081522')); c.setStrokeColor(HexColor(_COLORS.get(node.category, _COLORS['component'])))
        c.roundRect(x, y, w, h, max(3, 8 * scale), stroke=1, fill=1)
        c.setFillColor(HexColor('#f3f7ff')); c.setFont('Helvetica', max(7, min(12, 10 * scale)))
        text = node.label[:60]; tw = c.stringWidth(text, 'Helvetica', max(7, min(12, 10 * scale)))
        c.drawString(x + max(5, (w - tw) / 2), y + h / 2 - 3, text)
    c.showPage(); c.save()
    return output.getvalue()


def export_graph(graph: VisualGraph, fmt: str) -> tuple[bytes, str, str]:
    fmt = str(fmt or '').lower().strip()
    if fmt not in _FORMATS:
        raise ValueError(f'Unsupported export format: {fmt}. Supported: {", ".join(sorted(_FORMATS))}')
    safe_title = ''.join(ch if ch.isalnum() or ch in '-_' else '-' for ch in graph.title).strip('-')[:80] or 'visual'
    if fmt == 'html':
        return render_html(graph).encode('utf-8'), 'text/html; charset=utf-8', f'{safe_title}.html'
    if fmt == 'svg':
        return render_svg(graph).encode('utf-8'), 'image/svg+xml', f'{safe_title}.svg'
    if fmt == 'json':
        return json.dumps(graph.to_dict(), ensure_ascii=False, indent=2, sort_keys=True).encode('utf-8'), 'application/json', f'{safe_title}.json'
    if fmt in {'png', 'webp'}:
        mime = 'image/png' if fmt == 'png' else 'image/webp'
        return _raster(graph, fmt), mime, f'{safe_title}.{fmt}'
    return _pdf(graph), 'application/pdf', f'{safe_title}.pdf'
