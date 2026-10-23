"""Glyph outline extraction shared by reference matching and diagnostics."""

from __future__ import annotations

from dataclasses import dataclass

from fontTools.pens.recordingPen import DecomposingRecordingPen

_GRID = 16


@dataclass(frozen=True)
class GlyphShape:
    value: tuple[float, float, float, float]
    advance: float
    contours: int
    points: int
    bitmap: tuple[int, ...]


def _op_points(op, points):
    if not points:
        return []
    out = []
    for point in points:
        if point is None or len(point) < 2:
            continue
        x, y = point[0], point[1]
        if x is not None and y is not None:
            out.append((x, y))
    return out


def _polygons(recording):
    polygons = []
    current = []
    for op, points in recording:
        pts = _op_points(op, points)
        if op == "moveTo":
            if current:
                polygons.append(current)
            current = pts[:1]
        elif op in ("lineTo", "curveTo", "qCurveTo"):
            current.extend(pts)
        elif op in ("closePath", "endPath"):
            if current:
                if current[0] != current[-1]:
                    current.append(current[0])
                polygons.append(current)
                current = []
    if current:
        if len(current) > 1 and current[0] != current[-1]:
            current.append(current[0])
        polygons.append(current)
    return polygons


def _bitmap(polygons, bbox) -> tuple[int, ...]:
    x0, y0, x1, y1 = bbox
    width = max(x1 - x0, 1e-6)
    height = max(y1 - y0, 1e-6)
    cells = set()
    for polygon in polygons:
        for start, end in zip(polygon, polygon[1:]):
            sx, sy = start
            ex, ey = end
            length = max(abs(ex - sx), abs(ey - sy))
            steps = max(1, min(64, int(length / 12) + 1))
            for i in range(steps + 1):
                t = i / steps
                x = sx + (ex - sx) * t
                y = sy + (ey - sy) * t
                gx = min(_GRID - 1, max(0, int((x - x0) / width * _GRID)))
                gy = min(_GRID - 1, max(0, int((y - y0) / height * _GRID)))
                cells.add(gy * _GRID + gx)
    return tuple(sorted(cells))


def glyph_shape(glyph_set, name, hmtx, upm) -> GlyphShape:
    recording = DecomposingRecordingPen(glyph_set)
    glyph_set[name].draw(recording)
    polygons = _polygons(recording.value)
    points = [point for polygon in polygons for point in polygon]
    if not points:
        xs = ys = (0.0,)
        points = [(0.0, 0.0)]
    else:
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
    scale = 1000.0 / upm
    bbox = (min(xs) * scale, min(ys) * scale,
            max(xs) * scale, max(ys) * scale)
    return GlyphShape(
        value=bbox,
        advance=hmtx[name][0] * scale,
        contours=len(polygons),
        points=len(points),
        bitmap=_bitmap(polygons, (min(xs), min(ys), max(xs), max(ys))),
    )
