"""Full-window ROI locator and an independently zoomable question preview."""

from __future__ import annotations

from PySide6.QtCore import QDateTime, QEvent, QObject, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QScrollArea, QTabWidget, QVBoxLayout, QWidget


class Locator(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.image = QImage()
        self.region = QRect()
        self.setMinimumSize(240, 150)

    def paintEvent(self, _event: object) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        if self.image.isNull():
            painter.setPen(QColor("#667d75"))
            painter.drawText(self.rect().adjusted(12, 12, -12, -12), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                             "选择窗口并框选题目\n完整画面与高亮选区将显示在这里")
            return
        size = self.image.size().scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
        display = QRectF((self.width() - size.width()) / 2, (self.height() - size.height()) / 2, size.width(), size.height())
        painter.drawImage(display, self.image)
        if not self.region.isEmpty():
            scale = display.width() / self.image.width()
            selected = QRectF(display.x() + self.region.x() * scale, display.y() + self.region.y() * scale,
                              self.region.width() * scale, self.region.height() * scale)
            painter.save()
            from PySide6.QtGui import QPainterPath
            shade = QPainterPath()
            shade.addRect(display)
            hole = QPainterPath()
            hole.addRect(selected)
            painter.fillPath(shade.subtracted(hole), QColor(15, 37, 30, 125))
            painter.setPen(QPen(QColor("#54c7a5"), 2))
            painter.drawRect(selected.adjusted(1, 1, -1, -1))
            if selected.width() > 90 and selected.height() > 32:
                badge = QRectF(selected.left() + 3, selected.top() + 3, 64, 22)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor("#267563"))
                painter.drawRoundedRect(badge, 4, 4)
                painter.setPen(QColor("#ffffff"))
                painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, "已选题区")
            painter.restore()


class RegionPreview(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.image = QImage()  # Latest cropped image; no persistent history.
        self.full_image = QImage()
        self._fit = True
        self._zoom = 1.0
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(6)
        self.tabs = QTabWidget()
        self.locator = Locator()
        self.tabs.addTab(self.locator, "选区定位")
        detail = QWidget()
        detail_box = QVBoxLayout(detail)
        detail_box.setContentsMargins(0, 4, 0, 0)
        row = QHBoxLayout()
        for text, callback in (("−", lambda: self.zoom(.8)), ("＋", lambda: self.zoom(1.25)),
                               ("1:1", self.original), ("适应", self.fit)):
            item = QPushButton(text)
            item.clicked.connect(callback)
            row.addWidget(item)
        detail_box.addLayout(row)
        self.scroll = QScrollArea()
        self.scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.detail = QLabel("框选后可放大检查题目")
        self.detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scroll.setWidget(self.detail)
        self.scroll.viewport().installEventFilter(self)
        detail_box.addWidget(self.scroll, 1)
        self.tabs.addTab(detail, "题区细节")
        self.tabs.currentChanged.connect(lambda _index: QTimer.singleShot(0, self._refresh_detail))
        box.addWidget(self.tabs, 1)
        self.info = QLabel("按需刷新 · 空闲时不连续截图")
        self.info.setObjectName("muted")
        self.info.setWordWrap(True)
        box.addWidget(self.info)

    def set_frame(self, image: QImage, region: QRect) -> None:
        self.full_image = image.copy()
        self.locator.image, self.locator.region = self.full_image, QRect(region)
        self.locator.update()
        self.image = image.copy(region)
        self.info.setText(f"选区 {region.width()} × {region.height()} px · 更新于 {QDateTime.currentDateTime().toString('HH:mm:ss')}")
        self._refresh_detail()

    def set_image(self, image: QImage) -> None:
        self.image = image.copy()
        if self.full_image.isNull():
            self.set_frame(image, image.rect())
        self._refresh_detail()

    def clear(self) -> None:
        self.image = QImage()
        self.full_image = QImage()
        self.locator.image = QImage()
        self.locator.region = QRect()
        self.locator.update()
        self.detail.clear()
        self.info.setText("按需刷新 · 空闲时不连续截图")

    def fit(self) -> None:
        self._fit = True
        self._refresh_detail()

    def original(self) -> None:
        self._fit = False
        self._zoom = 1.0
        self._refresh_detail()

    def zoom(self, factor: float) -> None:
        if self._fit and not self.image.isNull():
            fitted = self.image.size().scaled(self.scroll.viewport().size(), Qt.AspectRatioMode.KeepAspectRatio)
            self._zoom = fitted.width() / self.image.width()
        self._fit = False
        self._zoom = max(.1, min(4.0, self._zoom * factor))
        self._refresh_detail()

    def _refresh_detail(self) -> None:
        if self.image.isNull():
            return
        size = self.image.size().scaled(self.scroll.viewport().size(), Qt.AspectRatioMode.KeepAspectRatio) if self._fit else self.image.size() * self._zoom
        self.detail.setPixmap(QPixmap.fromImage(self.image).scaled(size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        self.detail.resize(size)

    def resizeEvent(self, event: object) -> None:
        super().resizeEvent(event)
        self._refresh_detail()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.scroll.viewport() and event.type() == QEvent.Type.Resize and self._fit:
            QTimer.singleShot(0, self._refresh_detail)
        return super().eventFilter(watched, event)
