"""区域侵入判定（需求 FR-09）。

规则（与 docs/api.md §6 一致）：
- 判定依据是**检测框中心点**；
- 边界上的点默认算作区域内（`settings.region_boundary_inclusive`）；
- 命中任一区域即算侵入。

用射线法判断点是否在多边形内，矩形只是 4 个顶点的多边形——
这样矩形和多边形共用一套代码，不用写两遍。
"""

from __future__ import annotations

Point = tuple[float, float]


def _on_segment(p: Point, a: Point, b: Point, eps: float = 1e-9) -> bool:
    """点是否落在线段 ab 上（含端点）。用叉积判共线 + 范围判在段内。"""
    cross = (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])
    if abs(cross) > eps:
        return False
    return (
        min(a[0], b[0]) - eps <= p[0] <= max(a[0], b[0]) + eps
        and min(a[1], b[1]) - eps <= p[1] <= max(a[1], b[1]) + eps
    )


def point_in_polygon(x: float, y: float, points: list[list[float]] | list[Point]) -> bool:
    """射线法：从点向右发射水平射线，统计与多边形边的交点个数。"""
    n = len(points)
    if n < 3:
        return False
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = float(points[i][0]), float(points[i][1])
        xj, yj = float(points[j][0]), float(points[j][1])
        # 判断射线 (x,y)->(+inf,y) 是否跨越边 (i,j)
        if (yi > y) != (yj > y):
            x_cross = (xj - xi) * (y - yi) / (yj - yi) + xi
            if x_cross > x:
                inside = not inside
        j = i
    return inside


def point_on_boundary(x: float, y: float, points: list[list[float]] | list[Point]) -> bool:
    n = len(points)
    j = n - 1
    for i in range(n):
        a = (float(points[i][0]), float(points[i][1]))
        b = (float(points[j][0]), float(points[j][1]))
        if _on_segment((x, y), a, b):
            return True
        j = i
    return False


def region_contains(
    points: list[list[float]] | list[Point],
    x: float,
    y: float,
    *,
    boundary_inclusive: bool = True,
) -> bool:
    """点是否在区域内。"""
    if boundary_inclusive and point_on_boundary(x, y, points):
        return True
    return point_in_polygon(x, y, points)


def bbox_center(x1: float, y1: float, x2: float, y2: float) -> Point:
    return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)
