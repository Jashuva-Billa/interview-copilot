"""Overlay UI — invisible in screen share (Windows + macOS)."""

from __future__ import annotations

from PyQt6.QtCore import QEvent, QPoint, QRect, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QFont,
    QGuiApplication,
    QKeySequence,
    QPainter,
    QPalette,
    QShortcut,
    QWheelEvent,
)
from PyQt6.QtWidgets import (
    QApplication,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

import config
from capture_exclude import apply_to_window
from glass_effect import apply_glass_backdrop
from glass_theme import stylesheet as glass_stylesheet
from response_parser import ParsedResponse

_DRAG_STRIP_H = 28
_RESIZE_GRIP = 22


class _DragStrip(QWidget):
    """Top bar — drag to move (visible + hit-testable on Windows)."""

    def __init__(self, window: QMainWindow):
        super().__init__()
        self._window = window
        self._offset: QPoint | None = None
        self.setObjectName("drag_strip")
        self.setFixedHeight(_DRAG_STRIP_H)
        self.setToolTip("Drag here to move the window")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        grip = QLabel("⋮⋮⋮  drag to move")
        grip.setObjectName("drag_grip")
        grip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row = QVBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(grip)

    def paintEvent(self, event) -> None:
        # Minimal fill so Windows registers mouse hits (invisible in see-through mode)
        if not (config.GLASS_SEE_THROUGH and config.GLASS_PANEL_TINT_PERCENT <= 1):
            painter = QPainter(self)
            painter.fillRect(self.rect(), QColor(255, 255, 255, 12))
            painter.end()
        super().paintEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._offset = event.globalPosition().toPoint() - self._window.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self._window.move(event.globalPosition().toPoint() - self._offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._offset = None
        super().mouseReleaseEvent(event)


class _ResizeGrip(QWidget):
    """Bottom-right corner — drag to resize."""

    def __init__(self, window: QMainWindow):
        super().__init__()
        self._window = window
        self._origin: QPoint | None = None
        self._start_size: QPoint | None = None
        self.setObjectName("resize_grip")
        self.setFixedSize(_RESIZE_GRIP, _RESIZE_GRIP)
        self.setToolTip("Drag to resize window")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(255, 255, 255, 40))
        painter.setPen(QColor(255, 255, 255, 220))
        w, h = self.width(), self.height()
        for i in range(3):
            o = 4 + i * 5
            painter.drawLine(w - o, h - 4, w - 4, h - o)
        painter.end()
        super().paintEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._origin = event.globalPosition().toPoint()
            self._start_size = QPoint(self._window.width(), self._window.height())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if (
            self._origin is not None
            and self._start_size is not None
            and event.buttons() & Qt.MouseButton.LeftButton
        ):
            delta = event.globalPosition().toPoint() - self._origin
            w = max(self._window.minimumWidth(), self._start_size.x() + delta.x())
            h = max(self._window.minimumHeight(), self._start_size.y() + delta.y())
            self._window.resize(w, h)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._origin = None
        self._start_size = None
        super().mouseReleaseEvent(event)


class OverlayWindow(QMainWindow):
    answer_ready = pyqtSignal(object)
    status_changed = pyqtSignal(str)
    listening_toggled = pyqtSignal(bool)
    force_coding_requested = pyqtSignal()
    scan_screen_requested = pyqtSignal()
    watch_screen_toggled = pyqtSignal(bool)

    def __init__(self):
        super().__init__()
        self._listening = False
        self._coding_visible = False
        self._last_question = ""
        self._transparent = config.use_transparent_overlay()
        self._share_hide_ok = False
        self._applying_exclude = False
        self._glass_applied = False
        self._layout_mode = "normal"
        self._saved_normal_geometry: QRect | None = None
        self._code_box_max_default = 200
        self._setup_ui()
        self.installEventFilter(self)
        self.answer_ready.connect(self._set_response)

        self._exclude_debounce = QTimer(self)
        self._exclude_debounce.setSingleShot(True)
        self._exclude_debounce.timeout.connect(self._apply_exclude_once)

        if config.EXCLUDE_REFRESH_SEC > 0:
            self._exclude_slow = QTimer(self)
            self._exclude_slow.timeout.connect(self._apply_exclude_once)
            self._exclude_slow.start(config.EXCLUDE_REFRESH_SEC * 1000)

    def _setup_ui(self) -> None:
        self.setWindowTitle("Interview Copilot")
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        if config.STEALTH_FOCUS:
            flags = flags | Qt.WindowType.WindowDoesNotAcceptFocus
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setWindowFlags(flags)
        if self._transparent:
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        else:
            self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setMinimumSize(420, 320)
        self.resize(680, 520)

        central = QWidget()
        central.setObjectName("panel")
        if self._transparent:
            central.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            central.setAutoFillBackground(False)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)

        self._drag_strip = _DragStrip(self)
        if self._transparent:
            self._drag_strip.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        layout.addWidget(self._drag_strip)

        header = QHBoxLayout()
        title = QLabel("Interview Copilot")
        title.setObjectName("title")
        header.addWidget(title)
        header.addStretch()

        self.btn_coding = QPushButton("Coding")
        self.btn_coding.setObjectName("ghost")
        self.btn_coding.setCheckable(True)
        self.btn_coding.clicked.connect(self._on_force_coding_click)
        header.addWidget(self.btn_coding)

        self.btn_scan = QPushButton("Scan screen")
        self.btn_scan.setObjectName("primary")
        self.btn_scan.clicked.connect(self._on_scan_click)
        header.addWidget(self.btn_scan)

        self.btn_watch = QPushButton("Watch")
        self.btn_watch.setObjectName("ghost")
        self.btn_watch.setCheckable(True)
        self.btn_watch.toggled.connect(self._on_watch_toggle)
        header.addWidget(self.btn_watch)

        self.btn_listen = QPushButton("Start listening")
        self.btn_listen.setObjectName("primary")
        self.btn_listen.clicked.connect(self._on_listen_click)
        header.addWidget(self.btn_listen)

        self.btn_close = QPushButton("✕")
        self.btn_close.setObjectName("close")
        self.btn_close.setFixedSize(30, 30)
        self.btn_close.setToolTip("Exit Interview Copilot")
        self.btn_close.clicked.connect(self._exit_app)
        header.addWidget(self.btn_close)

        layout.addLayout(header)

        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("status")
        layout.addWidget(self.status_label)

        layout.addWidget(QLabel("Question", objectName="section"))
        self.question_box = QTextEdit()
        self.question_box.setReadOnly(True)
        self.question_box.setMaximumHeight(72)
        self._make_see_through_edit(self.question_box)
        layout.addWidget(self.question_box)

        self.approach_label = QLabel("What to say (approach)")
        self.approach_label.setObjectName("section")
        layout.addWidget(self.approach_label)
        self.answer_box = QTextEdit()
        self.answer_box.setReadOnly(True)
        self._make_see_through_edit(self.answer_box)
        layout.addWidget(self.answer_box, stretch=1)

        code_header = QHBoxLayout()
        code_header.addWidget(QLabel("Code", objectName="section"))
        code_header.addStretch()
        self.btn_copy = QPushButton("Copy code")
        self.btn_copy.setObjectName("primary")
        self.btn_copy.clicked.connect(self._on_copy_click)
        code_header.addWidget(self.btn_copy)

        self.code_section = QWidget()
        self._make_translucent_widget(self.code_section)
        csl = QVBoxLayout(self.code_section)
        csl.setContentsMargins(0, 0, 0, 0)
        csl.addLayout(code_header)
        self.code_box = QPlainTextEdit()
        self.code_box.setReadOnly(True)
        self._make_see_through_edit(self.code_box)
        mono = QFont("Menlo" if config.IS_MAC else "Consolas", 13)
        self.code_box.setFont(mono)
        self.code_box.setMaximumHeight(200)
        csl.addWidget(self.code_box)
        layout.addWidget(self.code_section)
        self.code_section.hide()

        hint = QLabel("Hover + scroll here · drag top bar to move · Ctrl+H hide")
        hint.setObjectName("hint")
        layout.addWidget(hint)

        resize_row = QHBoxLayout()
        resize_row.setContentsMargins(0, 0, 0, 0)
        resize_row.addStretch()
        self._resize_grip = _ResizeGrip(self)
        resize_row.addWidget(self._resize_grip)
        layout.addLayout(resize_row)

        self.setCentralWidget(central)
        self._central_panel = central
        self._install_edge_filters(central)
        if config.STEALTH_FOCUS:
            self._apply_stealth_focus(central)
        see_through = config.GLASS_SEE_THROUGH and self._transparent
        if see_through:
            for w in (
                self.findChild(QLabel, "title"),
                self.status_label,
                self.approach_label,
                self.findChild(QLabel, "hint"),
                self.question_box,
                self.answer_box,
                self.code_box,
            ):
                if w is not None:
                    self._apply_text_halo(w)
            for w in central.findChildren(QLabel, "section"):
                self._apply_text_halo(w)
        elif self._transparent:
            for w in (
                self.findChild(QLabel, "title"),
                self.status_label,
                self.approach_label,
                self.findChild(QLabel, "hint"),
            ):
                if w is not None:
                    self._apply_text_halo(w)
            for w in central.findChildren(QLabel, "section"):
                self._apply_text_halo(w)
        else:
            self._apply_panel_shadow(central)
        self.setStyleSheet(glass_stylesheet(transparent=self._transparent))
        QApplication.setFont(QFont("Segoe UI" if config.IS_WINDOWS else ".AppleSystemUIFont", 12))

        QShortcut(QKeySequence("Ctrl+H"), self, self.hide)
        QShortcut(QKeySequence("Ctrl+Shift+H"), self, self._show_and_exclude)
        QShortcut(QKeySequence("Ctrl+Shift+C"), self, self._shortcut_force_coding)
        QShortcut(QKeySequence("Ctrl+Shift+S"), self, self._on_scan_click)
        QShortcut(QKeySequence("Escape"), self, self._exit_app)

    def _make_translucent_widget(self, widget: QWidget) -> None:
        if self._transparent:
            widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            widget.setAutoFillBackground(False)

    def _make_see_through_edit(self, edit: QTextEdit | QPlainTextEdit) -> None:
        """Force text areas transparent so background desktop text shows through."""
        self._make_translucent_widget(edit)
        pal = edit.palette()
        pal.setColor(QPalette.ColorRole.Base, QColor(0, 0, 0, 0))
        pal.setColor(QPalette.ColorRole.Text, QColor(255, 255, 255))
        edit.setPalette(pal)
        edit.setStyleSheet(
            "background: transparent; background-color: transparent; border: none;"
        )

    def _apply_stealth_focus(self, central: QWidget) -> None:
        """Hover + wheel scroll without focusing the overlay (keeps coding tab active)."""
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        central.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        for box in (self.question_box, self.answer_box, self.code_box):
            box.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            box.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        for btn in (
            self.btn_coding,
            self.btn_scan,
            self.btn_watch,
            self.btn_listen,
            self.btn_copy,
            self.btn_close,
        ):
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def _scroll_target_at(self, global_pos: QPoint) -> QTextEdit | QPlainTextEdit | None:
        panel = getattr(self, "_central_panel", None)
        if panel is None:
            return None
        local = panel.mapFromGlobal(global_pos)
        w = panel.childAt(local)
        while w is not None:
            if isinstance(w, (QTextEdit, QPlainTextEdit)):
                return w
            w = w.parentWidget()
        return None

    @staticmethod
    def _apply_wheel_scroll(target: QTextEdit | QPlainTextEdit, delta_y: int) -> None:
        bar = target.verticalScrollBar()
        step = max(20, abs(delta_y) // 3)
        bar.setValue(bar.value() - step if delta_y > 0 else bar.value() + step)

    @staticmethod
    def _apply_text_halo(widget: QWidget) -> None:
        """Shadow so white copilot text stays readable over background bleed-through."""
        fx = QGraphicsDropShadowEffect(widget)
        fx.setBlurRadius(6)
        fx.setOffset(0, 1)
        fx.setColor(QColor(0, 0, 0, 160))
        widget.setGraphicsEffect(fx)

    @staticmethod
    def _apply_panel_shadow(panel: QWidget) -> None:
        fx = QGraphicsDropShadowEffect(panel)
        fx.setBlurRadius(28)
        fx.setOffset(0, 6)
        fx.setColor(QColor(0, 0, 0, 70))
        panel.setGraphicsEffect(fx)

    def _apply_glass_backdrop(self) -> None:
        if not self._transparent or self._glass_applied:
            return
        if config.GLASS_BLUR_PERCENT <= 0:
            return
        if apply_glass_backdrop(self, config.GLASS_BLUR_PERCENT):
            self._glass_applied = True

    def _install_edge_filters(self, root: QWidget) -> None:
        root.installEventFilter(self)
        for child in root.findChildren(QWidget):
            child.installEventFilter(self)

    def _apply_stealth_win32(self) -> None:
        if not config.STEALTH_FOCUS or not config.IS_WINDOWS:
            return
        try:
            from win_stealth import prevent_activation_steal

            handle = self.windowHandle()
            hwnd = int(handle.winId()) if handle is not None else int(self.winId())
            prevent_activation_steal(hwnd)
        except Exception:
            pass

    def eventFilter(self, obj, event) -> bool:
        et = event.type()

        if et == QEvent.Type.Wheel and isinstance(event, QWheelEvent) and config.STEALTH_FOCUS:
            target = self._scroll_target_at(event.globalPosition().toPoint())
            if target is not None:
                self._apply_wheel_scroll(target, event.angleDelta().y())
                event.accept()
                return True

        return False

    def wheelEvent(self, event: QWheelEvent) -> None:
        if config.STEALTH_FOCUS:
            target = self._scroll_target_at(event.globalPosition().toPoint())
            if target is not None:
                self._apply_wheel_scroll(target, event.angleDelta().y())
                event.accept()
                return
        super().wheelEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.schedule_exclude()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.schedule_exclude()
        QTimer.singleShot(80, self._apply_glass_backdrop)
        if config.STEALTH_FOCUS:
            QTimer.singleShot(100, self._apply_stealth_win32)

    def show(self) -> None:
        super().show()
        self.raise_()
        if not config.STEALTH_FOCUS:
            self.activateWindow()
        self.schedule_exclude()

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() in (QEvent.Type.WindowActivate, QEvent.Type.Show):
            self.schedule_exclude()

    def schedule_exclude(self) -> None:
        """Debounced — avoids freezing UI on Windows."""
        self._exclude_debounce.start(200)

    def _apply_exclude_once(self) -> None:
        if not config.INVISIBLE_IN_SHARE or self._applying_exclude:
            return
        self._applying_exclude = True
        try:
            ok, note = apply_to_window(self)
            self._share_hide_ok = ok
            if note and not ok:
                self.status_label.setText(note)
        finally:
            self._applying_exclude = False

    def _show_and_exclude(self) -> None:
        self.show()
        self._apply_exclude_once()

    def hide_for_screenshot(self) -> None:
        self.hide()

    def restore_after_screenshot(self) -> None:
        self.show()
        QTimer.singleShot(100, self._apply_exclude_once)

    def _exit_app(self) -> None:
        app = QApplication.instance()
        if app is not None:
            app.quit()
        else:
            self.close()

    def _on_listen_click(self) -> None:
        self._listening = not self._listening
        self.btn_listen.setText("Stop listening" if self._listening else "Start listening")
        self.listening_toggled.emit(self._listening)
        self.schedule_exclude()

    def _on_force_coding_click(self) -> None:
        self.force_coding_requested.emit()
        self.schedule_exclude()

    def _on_scan_click(self) -> None:
        self.scan_screen_requested.emit()
        self.schedule_exclude()

    def _on_watch_toggle(self, checked: bool) -> None:
        self.watch_screen_toggled.emit(checked)
        self.schedule_exclude()

    def _on_copy_click(self) -> None:
        code = self.code_box.toPlainText().strip()
        if code:
            QGuiApplication.clipboard().setText(code)
            self.status_label.setText("Code copied")
        self.schedule_exclude()

    def _shortcut_force_coding(self) -> None:
        self.btn_coding.setChecked(True)
        self._on_force_coding_click()

    def set_listening_state(self, listening: bool) -> None:
        self._listening = listening
        self.btn_listen.setText("Stop listening" if listening else "Start listening")

    def apply_coding_layout(self) -> None:
        """Tall strip on the left — room for approach + code top to bottom."""
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        avail = screen.availableGeometry()
        if self._layout_mode != "coding":
            self._saved_normal_geometry = self.geometry()
        self._layout_mode = "coding"
        margin = 10
        width = min(500, max(360, int(avail.width() * 0.34)))
        self.setGeometry(
            avail.x() + margin,
            avail.y() + margin,
            width,
            avail.height() - 2 * margin,
        )
        self.question_box.setMaximumHeight(56)
        self.code_box.setMaximumHeight(16_777_215)

    def apply_normal_layout(self) -> None:
        """Restore compact window after behavioral / non-coding answers."""
        if self._layout_mode == "coding":
            if self._saved_normal_geometry is not None:
                self.setGeometry(self._saved_normal_geometry)
            else:
                self.resize(680, 520)
                self.move(80, 80)
        self._layout_mode = "normal"
        self.question_box.setMaximumHeight(72)
        self.code_box.setMaximumHeight(self._code_box_max_default)

    def _set_response(self, response: ParsedResponse) -> None:
        if response.is_coding or response.code:
            self.code_section.show()
            self.approach_label.setText("What to say (approach)")
            self.answer_box.setPlainText(response.approach or response.full_text)
            self.code_box.setPlainText(response.code)
            self.btn_coding.setChecked(False)
            self.apply_coding_layout()
        else:
            self.code_section.hide()
            self.approach_label.setText("Suggested answer")
            self.answer_box.setPlainText(response.full_text)
            self.apply_normal_layout()
        self.schedule_exclude()

    def set_watch_checked(self, checked: bool) -> None:
        self.btn_watch.setChecked(checked)

    def set_question(self, text: str) -> None:
        self._last_question = text
        self.question_box.setPlainText(text)

    def set_question_preview(self, text: str) -> None:
        """Update the live transcript without resetting answer panels."""
        self._last_question = text
        self.question_box.setPlainText(text)

    def get_last_question(self) -> str:
        return self._last_question

    # Back-compat for main.py
    def ensure_invisible_to_share(self) -> None:
        self.schedule_exclude()
