"""Toolpath preview: 2D plot by default, optional 3D view."""

from __future__ import annotations

import bisect
import time
from typing import Any

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..core.gcode_parser import ProgramLine, Segment, Toolpath, build_toolpath
from .job_panel import format_duration
from .theme import tokens


def _segment_points(segment: Segment) -> list[tuple[float, float, float]]:
    return segment.points if len(segment.points) > 1 else [segment.start, segment.end]


class Visualizer(QWidget):
    def __init__(self, token: dict[str, str] | None = None, parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self._token = token or tokens()
        self.setObjectName("Panel")
        self._segments: list[Segment] = []
        self._segment_lines: list[int] = []
        self._offsets: list[int] = []
        self._points = np.empty((0, 2))
        self._points_3d = np.empty((0, 3))
        self._last_render = 0.0
        self._pending_line: int | None = None
        self._executed_offset = 0
        self._toolpath: Toolpath | None = None
        self._marker_3d: Any = None
        self._remaining_3d: Any = None
        self._executed_3d: Any = None
        self._gl: Any = None

        self._plot = pg.PlotWidget(background=self._token["editor"])
        self._plot.showGrid(x=True, y=True, alpha=0.12)
        self._plot.setAspectLocked(True)
        # Mouse wheel zooms, left-drag pans (pyqtgraph defaults, made explicit).
        self._plot.setMouseEnabled(x=True, y=True)
        self._plot.setLabel("bottom", "X", units="mm")
        self._plot.setLabel("left", "Y", units="mm")
        self._plot.getAxis("bottom").setPen(pg.mkPen(self._token["border"]))
        self._plot.getAxis("left").setPen(pg.mkPen(self._token["border"]))
        for axis in ("bottom", "left"):
            self._plot.getAxis(axis).setTextPen(pg.mkPen(self._token["muted"]))

        self._remaining = pg.PlotDataItem(
            pen=pg.mkPen(self._token["muted"], width=1, style=Qt.PenStyle.DashLine)
        )
        self._executed = pg.PlotDataItem(pen=pg.mkPen(self._token["idle"], width=1.6))
        self._marker = pg.ScatterPlotItem(
            size=11,
            brush=pg.mkBrush(self._token["accent"]),
            pen=pg.mkPen(self._token["window"]),
        )
        self._plot.addItem(self._remaining)
        self._plot.addItem(self._executed)
        self._plot.addItem(self._marker)
        self._marker.hide()

        self._stack = QStackedWidget()
        self._stack.addWidget(self._plot)
        self._placeholder = QLabel("3D view is unavailable (PyOpenGL is not installed).")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._stack.addWidget(self._placeholder)
        self._gl = None

        header = QLabel("TOOLPATH")
        header.setObjectName("SectionHeader")
        self._zoom_out_button = QPushButton("−")
        self._zoom_out_button.setFixedWidth(30)
        self._zoom_out_button.setToolTip("Zoom out (⌘− or scroll)")
        self._zoom_out_button.setAccessibleName("Zoom out")
        self._zoom_out_button.clicked.connect(self.zoom_out)
        self._zoom_in_button = QPushButton("+")
        self._zoom_in_button.setFixedWidth(30)
        self._zoom_in_button.setToolTip("Zoom in (⌘+ or scroll)")
        self._zoom_in_button.setAccessibleName("Zoom in")
        self._zoom_in_button.clicked.connect(self.zoom_in)
        self._fit = QPushButton("Fit")
        self._fit.setToolTip("Fit the toolpath in view (F or ⌘0)")
        self._fit.clicked.connect(self.fit)
        self._two_d = QPushButton("2D")
        self._three_d = QPushButton("3D")
        for button in (self._two_d, self._three_d):
            button.setCheckable(True)
            button.setFixedWidth(40)
        self._two_d.setChecked(True)
        self._two_d.clicked.connect(lambda: self._set_view(2))
        self._three_d.clicked.connect(lambda: self._set_view(3))

        top = QHBoxLayout()
        top.addWidget(header)
        top.addStretch(1)
        top.addWidget(self._two_d)
        top.addWidget(self._three_d)
        top.addWidget(self._zoom_out_button)
        top.addWidget(self._zoom_in_button)
        top.addWidget(self._fit)

        self._info = QLabel("No file loaded")
        self._info.setObjectName("Muted")
        self._legend = QLabel()
        self._legend.setObjectName("Legend")
        self._update_legend()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)
        layout.addLayout(top)
        layout.addWidget(self._stack, 1)
        layout.addWidget(self._legend)
        layout.addWidget(self._info)

        self._throttle = QTimer(self)
        self._throttle.setSingleShot(True)
        self._throttle.setInterval(140)
        self._throttle.timeout.connect(self._flush)

    # ------------------------------------------------------------------ #
    def set_token(self, token: dict[str, str]) -> None:
        self._token = token
        self._plot.setBackground(token["editor"])
        self._plot.getAxis("bottom").setPen(pg.mkPen(token["border"]))
        self._plot.getAxis("left").setPen(pg.mkPen(token["border"]))
        for axis in ("bottom", "left"):
            self._plot.getAxis(axis).setTextPen(pg.mkPen(token["muted"]))
        self._remaining.setPen(pg.mkPen(token["muted"], width=1, style=Qt.PenStyle.DashLine))
        self._executed.setPen(pg.mkPen(token["idle"], width=1.6))
        self._marker.setBrush(pg.mkBrush(token["accent"]))
        self._marker.setPen(pg.mkPen(token["window"]))
        if self._gl is not None:
            self._gl.setBackgroundColor(token["editor"])
            if self._executed_3d is not None:
                self._executed_3d.setColor(pg.glColor(token["idle"]))
            if self._marker_3d is not None:
                self._marker_3d.setColor(pg.glColor(token["accent"]))

    @property
    def toolpath(self):  # noqa: ANN201
        return self._toolpath

    def set_program(self, program: list[ProgramLine], limits=None) -> None:  # noqa: ANN001
        self._toolpath = build_toolpath(program, limits=limits)
        self._segments = self._toolpath.segments
        self._segment_lines = [segment.source_line for segment in self._segments]
        self._points, self._offsets = self._build_arrays(self._segments, 2)
        self._points_3d, _ = self._build_arrays(self._segments, 3)
        self._executed.setData(x=self._points[:0, 0], y=self._points[:0, 1], connect="finite")
        self._remaining.setData(x=self._points[:, 0], y=self._points[:, 1], connect="finite")
        self._marker.hide()
        self._last_render = 0.0
        self._pending_line = None
        self._update_info()
        if self._gl is not None:
            self._refresh_3d()
        self.fit()

    def clear(self) -> None:
        self._segments = []
        self._segment_lines = []
        self._offsets = []
        self._points = np.empty((0, 2))
        self._points_3d = np.empty((0, 3))
        self._executed.setData(x=[], y=[])
        self._remaining.setData(x=[], y=[])
        self._marker.hide()
        self._info.setText("No file loaded")
        self._placeholder.setText("3D view is unavailable")
        if self._gl is not None:
            self._refresh_3d()

    def set_progress_line(self, line: int, force: bool = False) -> None:
        if not self._segments:
            return
        now = time.monotonic()
        if not force and now - self._last_render < 0.15:
            self._pending_line = line
            if not self._throttle.isActive():
                self._throttle.start()
            return
        self._apply_line(line)

    def _flush(self) -> None:
        if self._pending_line is not None:
            self._apply_line(self._pending_line)
            self._pending_line = None

    def _apply_line(self, line: int) -> None:
        count = bisect.bisect_right(self._segment_lines, line)
        offset = self._offsets[count - 1] if count else 0
        executed = self._points[:offset]
        remaining = self._points[offset:]
        self._executed.setData(x=executed[:, 0], y=executed[:, 1], connect="finite")
        self._remaining.setData(x=remaining[:, 0], y=remaining[:, 1], connect="finite")
        self._last_render = time.monotonic()
        if self._gl is not None:
            self._refresh_3d(offset)

    def set_position(self, x: float | None, y: float | None, z: float | None) -> None:
        if x is None or y is None:
            self._marker.hide()
            return
        self._marker.setData([x], [y])
        self._marker.show()
        if self._gl is not None and self._marker_3d is not None:
            self._marker_3d.setData(
                pos=np.array([[x, y, z or 0.0]]), color=pg.glColor(self._token["accent"])
            )
            self._marker_3d.setVisible(True)

    def zoom_in(self) -> None:
        self.zoom(0.8)

    def zoom_out(self) -> None:
        self.zoom(1.25)

    def zoom(self, factor: float) -> None:
        """Zoom by *factor* (<1 zooms in, >1 zooms out) in 2D or 3D."""
        if factor <= 0:
            return
        if self._stack.currentIndex() == 1:
            if self._gl is None:
                return
            distance = float(self._gl.opts.get("distance", 10.0))
            self._gl.setCameraPosition(distance=max(0.05, distance * factor))
            self._gl.update()
            return
        self._plot.getViewBox().scaleBy((factor, factor))
        self._plot.update()

    def _update_legend(self) -> None:
        if self._stack.currentIndex() == 1:
            self._legend.setText("drag to rotate · scroll or +/− to zoom")
        else:
            self._legend.setText(
                "green = executed · dashed = remaining · scroll or +/− to zoom · drag to pan"
            )

    def fit(self) -> None:
        if self._toolpath is None or self._toolpath.bounds is None:
            self._plot.setRange(xRange=(-10, 10), yRange=(-10, 10), padding=0)
            return
        low, high = self._toolpath.bounds
        width = max(high[0] - low[0], 1.0)
        height = max(high[1] - low[1], 1.0)
        margin = max(width, height) * 0.08
        self._plot.setRange(
            xRange=(low[0] - margin, high[0] + margin),
            yRange=(low[1] - margin, high[1] + margin),
            padding=0,
        )
        if self._gl is not None:
            span = max(width, height, high[2] - low[2], 1.0)
            self._gl.opts["center"] = pg.Vector(
                (low[0] + high[0]) / 2, (low[1] + high[1]) / 2, (low[2] + high[2]) / 2
            )
            self._gl.setCameraPosition(distance=span * 2.2, elevation=32, azimuth=45)
            self._gl.update()

    # ------------------------------------------------------------------ #
    def _set_view(self, dimensions: int) -> None:
        if dimensions == 2:
            self._two_d.setChecked(True)
            self._three_d.setChecked(False)
            self._stack.setCurrentIndex(0)
            self._update_legend()
            return
        self._ensure_3d()
        if self._gl is None:
            self._three_d.setChecked(False)
            self._two_d.setChecked(True)
            return
        self._two_d.setChecked(False)
        self._three_d.setChecked(True)
        self._stack.setCurrentIndex(1)
        self._update_legend()
        self._refresh_3d()
        self.fit()

    def _ensure_3d(self) -> None:
        if self._gl is not None:
            return
        try:
            import pyqtgraph.opengl as gl

            view = gl.GLViewWidget()
            view.setBackgroundColor(self._token["editor"])
            grid = gl.GLGridItem()
            grid.setSize(200, 200, 10)
            grid.setSpacing(10, 10)
            view.addItem(grid)
            axes = gl.GLAxisItem()
            axes.setSize(20, 20, 20)
            view.addItem(axes)
            self._remaining_3d = gl.GLLinePlotItem(color=(0.55, 0.58, 0.63, 1.0), width=1)
            self._executed_3d = gl.GLLinePlotItem(color=pg.glColor(self._token["idle"]), width=2)
            self._marker_3d = gl.GLScatterPlotItem(
                pos=np.empty((0, 3)), color=pg.glColor(self._token["accent"]), size=10
            )
            for item in (self._remaining_3d, self._executed_3d, self._marker_3d):
                view.addItem(item)
            self._gl = view
            self._marker_3d.setVisible(False)
            self._stack.removeWidget(self._placeholder)
            self._stack.addWidget(view)
            self._three_d.setEnabled(True)
            self._three_d.setToolTip("3D view")
        except Exception:  # noqa: BLE001
            self._gl = None
            self._placeholder.setText("3D view could not be initialised on this system.")
            self._three_d.setToolTip("3D view unavailable")
            self._three_d.setEnabled(False)

    def _refresh_3d(self, offset: int | None = None) -> None:
        if self._gl is None or self._remaining_3d is None or self._executed_3d is None:
            return
        if offset is None:
            offset = self._executed_offset
        self._executed_offset = offset
        points = self._points_3d
        self._remaining_3d.setData(pos=points[offset:], mode="line_strip")
        self._executed_3d.setData(pos=points[:offset], mode="line_strip")

    def _build_arrays(
        self, segments: list[Segment], dimensions: int
    ) -> tuple[np.ndarray, list[int]]:
        total = sum(len(_segment_points(segment)) for segment in segments)
        stride = max(1, total // 40_000)
        rows: list[tuple[float, ...]] = []
        offsets: list[int] = []
        for segment in segments:
            points = _segment_points(segment)
            picked = points[::stride]
            if picked[-1] != points[-1]:
                picked.append(points[-1])
            for point in picked:
                rows.append(point[:dimensions])
            rows.append(tuple(float("nan") for _ in range(dimensions)))
            offsets.append(len(rows))
        if not rows:
            return np.empty((0, dimensions)), []
        return np.asarray(rows, dtype=float), offsets

    def _update_info(self) -> None:
        path = self._toolpath
        if path is None or not path.segments:
            self._info.setText("No drawable moves in this file")
            return
        low, high = path.bounds if path.bounds else ((0, 0, 0), (0, 0, 0))
        size = tuple(high[i] - low[i] for i in range(3))
        self._info.setText(
            f"{len(path.segments)} moves · {path.total_length:.0f} mm · "
            f"{format_duration(path.estimated_seconds)} · "
            f"{size[0]:.1f} × {size[1]:.1f} × {size[2]:.1f} mm"
        )
        if path.tools:
            self._info.setToolTip("Tools: " + ", ".join(f"T{tool}" for tool in path.tools))
        else:
            self._info.setToolTip("No tool changes in this file")
