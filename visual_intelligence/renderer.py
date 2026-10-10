from __future__ import annotations

from html import escape

from .models import VisualGraph


_COLORS = {
    'frontend': '#5EDBFF',
    'backend': '#66E0B7',
    'database': '#A78BFA',
    'security': '#FB7185',
    'cloud': '#F6C65B',
    'messagebus': '#FB923C',
    'agent': '#7DD3FC',
    'task': '#93C5FD',
    'work': '#C4B5FD',
    'goal': '#67E8F9',
    'milestone': '#FDE68A',
    'source': '#94A3B8',
    'tool': '#86EFAC',
    'project': '#60A5FA',
    'group': '#7C8CA5',
    'step': '#7DD3FC',
    'focus': '#60A5FA',
    'component': '#7DD3FC',
}


def _bounds(graph: VisualGraph):
    if not graph.nodes:
        return 0, 0, 1100, 700
    left = min(float(node.x or 0) for node in graph.nodes) - 70
    top = min(float(node.y or 0) for node in graph.nodes) - 70
    right = max(float(node.x or 0) + node.width for node in graph.nodes) + 90
    bottom = max(float(node.y or 0) + node.height for node in graph.nodes) + 90
    return left, top, max(800.0, right - left), max(520.0, bottom - top)


def render_svg(graph: VisualGraph) -> str:
    left, top, width, height = _bounds(graph)
    nodes = {node.id: node for node in graph.nodes}
    parts = [
        f'<svg class="vishnu-visual-svg" xmlns="http://www.w3.org/2000/svg" viewBox="{left:.0f} {top:.0f} {width:.0f} {height:.0f}" role="img" aria-label="{escape(graph.title)}">',
        '<defs><marker id="vv-arrow" markerWidth="9" markerHeight="9" refX="8" refY="4.5" orient="auto"><path d="M0,0 L9,4.5 L0,9 z" fill="#6F87A8"/></marker><filter id="vv-glow"><feGaussianBlur stdDeviation="3" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter></defs>',
        '<rect x="-10000" y="-10000" width="20000" height="20000" fill="#070B12"/>',
    ]
    for edge in graph.edges:
        source, target = nodes.get(edge.source), nodes.get(edge.target)
        if not source or not target:
            continue
        sx = float(source.x or 0) + source.width
        sy = float(source.y or 0) + source.height / 2
        tx = float(target.x or 0)
        ty = float(target.y or 0) + target.height / 2
        mx = (sx + tx) / 2
        path = f'M {sx:.1f} {sy:.1f} C {mx:.1f} {sy:.1f}, {mx:.1f} {ty:.1f}, {tx:.1f} {ty:.1f}'
        parts.append(f'<path data-edge-id="{escape(edge.id)}" d="{path}" fill="none" stroke="#536987" stroke-width="1.8" stroke-opacity=".78" marker-end="url(#vv-arrow)"/>')
        if edge.label:
            parts.append(f'<text x="{mx:.1f}" y="{(sy+ty)/2-7:.1f}" fill="#8798B0" text-anchor="middle" font-size="11">{escape(edge.label)}</text>')
    for node in graph.nodes:
        x, y = float(node.x or 0), float(node.y or 0)
        accent = _COLORS.get(node.category, '#7DD3FC')
        evidence = node.evidence_level.value.replace('_', ' ')
        parts.append(f'<g class="vv-node" tabindex="0" role="button" data-node-id="{escape(node.id)}" transform="translate({x:.1f} {y:.1f})">')
        parts.append(f'<rect width="{node.width:.1f}" height="{node.height:.1f}" rx="16" fill="#101722" stroke="#27364A" stroke-width="1"/>')
        parts.append(f'<rect x="0" y="0" width="4" height="{node.height:.1f}" rx="2" fill="{accent}"/>')
        parts.append(f'<circle cx="22" cy="23" r="5" fill="{accent}" filter="url(#vv-glow)"/>')
        parts.append(f'<text x="36" y="28" fill="#F5F7FB" font-size="14" font-family="-apple-system,BlinkMacSystemFont,Inter,sans-serif" font-weight="600">{escape(node.label[:40])}</text>')
        parts.append(f'<text x="18" y="51" fill="#8290A5" font-size="10" font-family="-apple-system,BlinkMacSystemFont,Inter,sans-serif">{escape(node.category.upper())} · {escape(evidence.upper())}</text>')
        parts.append('</g>')
    parts.append('</svg>')
    return ''.join(parts)


def render_html(graph: VisualGraph) -> str:
    svg = render_svg(graph)
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(graph.title)} · Vishnu Visualize</title>
<style>html,body{{margin:0;min-height:100%;background:#05080e;color:#f5f7fb;font-family:-apple-system,BlinkMacSystemFont,"Inter",sans-serif}}header{{padding:18px 22px;border-bottom:1px solid #1b2737;background:#0a1019}}header small{{color:#7f8da2}}main{{height:calc(100vh - 76px);overflow:auto}}svg{{width:100%;height:100%;min-width:760px;min-height:520px}}.vv-node{{cursor:pointer;outline:none}}.vv-node:focus rect,.vv-node:hover rect{{stroke:#70cfff;stroke-width:2}}</style></head>
<body><header><strong>{escape(graph.title)}</strong><br><small>Vishnu Visualize · {escape(graph.type.value.replace('_',' ').title())}</small></header><main>{svg}</main></body></html>'''
