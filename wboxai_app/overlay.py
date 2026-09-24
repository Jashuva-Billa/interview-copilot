"""Overlay UI — invisible in screen share (Windows 10/11)."""

from __future__ import annotations

from PyQt6.QtCore import (
    QEasingCurve,
    QEvent,
    QPoint,
    QPropertyAnimation,
    QRect,
    Qt,
    QTimer,
    pyqtProperty,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QAction,
    QActionGroup,
    QBrush,
    QColor,
    QFont,
    QGuiApplication,
    QIcon,
    QKeySequence,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QShortcut,
    QWheelEvent,
)
from PyQt6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSlider,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

import config
from capture_exclude import apply_to_window
from glass_effect import apply_glass_backdrop
from glass_theme import stylesheet as glass_stylesheet
from llm_project.response_parser import ParsedResponse

_DRAG_STRIP_H = 28
_RESIZE_GRIP = 22


class _ContrastLabel(QLabel):
    """Label text with a strong outline so it stays readable over any desktop."""

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        font = self.font()
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)

        metrics = painter.fontMetrics()
        text = self.text()
        text_rect = metrics.boundingRect(text)
        x = (self.width() - text_rect.width()) / 2 - text_rect.x()
        y = (self.height() + metrics.ascent() - metrics.descent()) / 2

        path = QPainterPath()
        path.addText(x, y, font, text)

        painter.setPen(QPen(QColor(0, 0, 0, 235), 4))
        painter.setBrush(QColor(255, 255, 255, 250))
        painter.drawPath(path)
        painter.setPen(QPen(QColor(255, 255, 255, 250), 1))
        painter.setBrush(QColor(255, 255, 255, 250))
        painter.drawPath(path)
        painter.end()


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
        grip = _ContrastLabel(":::  drag to move")
        grip.setObjectName("drag_grip")
        grip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Let the strip receive presses made directly on the label text.
        grip.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        row = QVBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(grip)

    def paintEvent(self, event) -> None:
        from PyQt6.QtWidgets import QStyleOption, QStyle
        opt = QStyleOption()
        opt.initFrom(self)
        painter = QPainter(self)
        self.style().drawPrimitive(QStyle.PrimitiveElement.PE_Widget, opt, painter, self)

        # Fully transparent pixels can be click-through on Windows layered
        # windows. Alpha 1 is invisible but keeps the whole strip hit-testable.
        alpha = (
            1
            if config.GLASS_SEE_THROUGH and config.GLASS_PANEL_TINT_PERCENT <= 1
            else 12
        )
        painter.fillRect(self.rect(), QColor(255, 255, 255, alpha))
        painter.end()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._offset = event.globalPosition().toPoint() - self._window.frameGeometry().topLeft()
            handle = self._window.windowHandle()
            if handle is not None and handle.startSystemMove():
                self._offset = None
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


class QToggleSwitch(QAbstractButton):
    def __init__(self, parent=None, text="", mini_thumb=True):
        super().__init__(parent)
        self.setText(text)
        self.setCheckable(True)
        self.setSizePolicy(self.sizePolicy().Policy.Fixed, self.sizePolicy().Policy.Fixed)
        self._is_mini_thumb = mini_thumb
        self._thumb_diameter = 14.0 if mini_thumb else 22.0
        self._thumb_position = 15.0 - (self._thumb_diameter / 2.0)
        
        self._animation = QPropertyAnimation(self, b"thumb_position", self)
        self._animation.setDuration(120)
        self._animation.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self._is_light = False
        
        self._height = 30
        self._width = max(68, len(text) * 7 + 32) if text else 52
        self.setFixedSize(self._width, self._height)
        
    @pyqtProperty(float)
    def thumb_position(self) -> float:
        return self._thumb_position
        
    @thumb_position.setter
    def thumb_position(self, pos: float) -> None:
        self._thumb_position = pos
        self.update()
        
    def nextCheckState(self) -> None:
        super().nextCheckState()
        start = self._thumb_position
        x_unchecked = 15.0 - (self._thumb_diameter / 2.0)
        x_checked = float(self.width()) - 15.0 - (self._thumb_diameter / 2.0)
        end = x_checked if self.isChecked() else x_unchecked
        self._animation.stop()
        self._animation.setStartValue(start)
        self._animation.setEndValue(end)
        self._animation.start()
        
    def setChecked(self, checked: bool) -> None:
        super().setChecked(checked)
        self._animation.stop()
        x_unchecked = 15.0 - (self._thumb_diameter / 2.0)
        x_checked = float(self.width()) - 15.0 - (self._thumb_diameter / 2.0)
        self._thumb_position = x_checked if checked else x_unchecked
        self.update()

    def set_light_mode(self, is_light: bool) -> None:
        if self._is_light != is_light:
            self._is_light = is_light
            self.update()
        
    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Colors: checked track uses Premium Blue, unchecked matches primary button
        bg_checked = QColor(59, 130, 246, 180)  # Matches QPushButton#primary:checked
        border_checked = QColor(59, 130, 246, 240)
        
        thumb_color = QColor(255, 255, 255) # Standard white thumb handle for contrast
        text_color = QColor(255, 255, 255)
        
        if self._is_light:
            bg_unchecked = QColor(0, 0, 0, 180)  # Matches QPushButton#primary on light bg
            border_unchecked = QColor(0, 0, 0, 60)
        else:
            bg_unchecked = QColor(0, 0, 0, 120)  # Matches QPushButton#primary on dark bg
            border_unchecked = QColor(255, 255, 255, 45)
            
        bg = bg_checked if self.isChecked() else bg_unchecked
        border_color = border_checked if self.isChecked() else border_unchecked
        
        rect = self.rect()
        radius = rect.height() / 2.0
        
        # Draw background track with borders to match push buttons
        p.setPen(QPen(border_color, 1))
        p.setBrush(QBrush(bg))
        p.drawRoundedRect(rect.x() + 1, rect.y() + 1, rect.width() - 2, rect.height() - 2, radius - 1, radius - 1)
        
        # Draw text inside track if present
        if self.text():
            p.setPen(text_color)
            font = QFont("Segoe UI", 10)
            p.setFont(font)
            if self.isChecked():
                # Thumb is on the right, draw text on the left
                text_rect = QRect(6, 0, self.width() - self.height() + 2, self.height())
                p.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, self.text())
            else:
                # Thumb is on the left, draw text on the right
                text_rect = QRect(self.height() - 6, 0, self.width() - self.height() + 2, self.height())
                p.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, self.text())
        
        # Draw thumb handle
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(thumb_color))
        y_coord = 15.0 - (self._thumb_diameter / 2.0)
        p.drawEllipse(int(self._thumb_position), int(y_coord), int(self._thumb_diameter), int(self._thumb_diameter))
        p.end()


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


def get_candidate_list() -> list[dict]:
    import urllib.request
    import json
    import config

    # Base mock candidates
    mocks = [
        {
            "name": "Jashuva",
            "role": "AI Engineer",
            "resume": {
                "name": "Jashuva",
                "skills": ["Python", "Generative AI", "LangGraph", "Milvus", "Redis", "AWS Bedrock", "MCP Servers"],
                "experience": [
                    {
                        "role": "AI Engineer",
                        "project": "Agentic AI Platform Migration",
                        "summary": "Modernized Enterprise RAG platform to Agentic AI utilizing LangGraph and Milvus vector db."
                    }
                ]
            }
        },
        {
            "name": "Alice Smith",
            "role": "Senior Cloud Solutions Architect",
            "resume": {
                "name": "Alice Smith",
                "skills": ["AWS", "GCP", "Terraform", "Kubernetes", "Python", "Docker"],
                "experience": [
                    {
                        "role": "Solutions Architect",
                        "project": "Microservices Migration",
                        "summary": "Led infrastructure automation using Terraform and migrated legacy monoliths to Kubernetes clusters."
                    }
                ]
            }
        },
        {
            "name": "Bob Johnson",
            "role": "Full Stack Engineer",
            "resume": {
                "name": "Bob Johnson",
                "skills": ["React", "Node.js", "PostgreSQL", "Redis", "TypeScript", "Docker"],
                "experience": [
                    {
                        "role": "Full Stack Developer",
                        "project": "Real-time Analytics Dashboard",
                        "summary": "Designed secure GraphQL APIs and optimized PostgreSQL database query execution time by 40%."
                    }
                ]
            }
        }
    ]

    if not config.CANDIDATE_API_URL:
        return mocks

    try:
        req = urllib.request.Request(config.CANDIDATE_API_URL, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=4) as response:
            data = json.loads(response.read().decode('utf-8'))
            if isinstance(data, list):
                res_list = []
                for item in data:
                    if not isinstance(item, dict):
                        continue
                    item_copy = dict(item)
                    if "name" not in item_copy:
                        item_copy["name"] = "Unknown"
                    if "role" not in item_copy:
                        item_copy["role"] = "Software Engineer"
                    if "resume" not in item_copy:
                        item_copy["resume"] = item_copy.copy()
                    res_list.append(item_copy)
                return res_list + mocks
            elif isinstance(data, dict) and "candidates" in data:
                res = data["candidates"]
                if isinstance(res, list):
                    res_list = []
                    for item in res:
                        if not isinstance(item, dict):
                            continue
                        item_copy = dict(item)
                        if "name" not in item_copy:
                            item_copy["name"] = "Unknown"
                        if "role" not in item_copy:
                            item_copy["role"] = "Software Engineer"
                        if "resume" not in item_copy:
                            item_copy["resume"] = item_copy.copy()
                        res_list.append(item_copy)
                    return res_list + mocks
    except Exception as e:
        print(f"[Candidates API] Failed to fetch from {config.CANDIDATE_API_URL}: {e}")
    
    return mocks


def show_resume_dialog(parent=None, whitebox_mode: bool | None = None) -> None:
    from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QTextEdit, QPushButton, QMessageBox, QLabel, QComboBox
    from PyQt6.QtCore import Qt
    import json
    import time
    import config

    dialog = QDialog(parent)
    dialog.setWindowTitle("Select Candidate for Interview Session")
    dialog.setMinimumSize(500, 420)
    dialog.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.WindowStaysOnTopHint)

    layout = QVBoxLayout(dialog)

    # Candidate drop-down selection
    lbl_select = QLabel("Select Candidate:")
    layout.addWidget(lbl_select)

    combo_candidates = QComboBox()
    
    # Load candidate list (API + mocks)
    candidates = get_candidate_list()
    for idx, cand in enumerate(candidates):
        combo_candidates.addItem(f"{cand['name']} ({cand['role']})", idx)
    layout.addWidget(combo_candidates)

    lbl_preview = QLabel("Resume Details Preview (JSON):")
    layout.addWidget(lbl_preview)

    text_preview = QTextEdit()
    layout.addWidget(text_preview)

    # Update preview helper
    def update_preview(index):
        if 0 <= index < len(candidates):
            cand = candidates[index]
            resume_data = cand.get("resume", cand)
            text_preview.setPlainText(json.dumps(resume_data, indent=2))

    combo_candidates.currentIndexChanged.connect(update_preview)
    # Trigger initial update
    if candidates:
        update_preview(0)

    btn_layout = QHBoxLayout()
    btn_start = QPushButton("Start WboxAI with Selected Candidate")
    btn_manual = QPushButton("Switch to Manual Edit")
    btn_layout.addWidget(btn_start)
    btn_layout.addWidget(btn_manual)
    layout.addLayout(btn_layout)

    # Whitebox mode: disable manual-edit switch (user already chose Whitebox)
    if whitebox_mode is True:
        btn_manual.setVisible(False)
        lbl_select.setText("Select Candidate (Whitebox):")

    # Manual mode start: open directly in editable state
    def switch_to_manual():
        text_preview.setReadOnly(False)
        combo_candidates.setEnabled(False)
        btn_start.setText("Save & Start WboxAI")
        btn_manual.setEnabled(False)
        QMessageBox.information(dialog, "Manual Mode", "You can now edit or paste any JSON resume directly in the text preview box.")

    btn_manual.clicked.connect(switch_to_manual)

    # For MANUAL mode, drop straight into editable state without a prompt
    if whitebox_mode is False:
        text_preview.setReadOnly(False)
        combo_candidates.setEnabled(False)
        btn_start.setText("Save & Start WboxAI")
        btn_manual.setVisible(False)
    else:
        text_preview.setReadOnly(True)  # read-only until manual switch clicked

    def on_start():
        content = text_preview.toPlainText().strip()
        if not content:
            QMessageBox.warning(dialog, "Empty Resume", "Resume content is empty.")
            return

        try:
            parsed = json.loads(content)
            formatted = json.dumps(parsed, indent=2)
            config.RESUME_PATH.write_text(formatted, encoding="utf-8")
            
            # Save candidate name and timestamp state
            if combo_candidates.isEnabled():
                idx = combo_candidates.currentIndex()
                config.SELECTED_CANDIDATE_NAME = candidates[idx]["name"]
            else:
                config.SELECTED_CANDIDATE_NAME = parsed.get("name", "ManualCandidate")
                
            config.SESSION_TIMESTAMP = time.strftime("%Y%m%d_%H%M%S")
            print(f"[config] Selected candidate: '{config.SELECTED_CANDIDATE_NAME}' at {config.SESSION_TIMESTAMP}", flush=True)
            dialog.accept()
        except json.JSONDecodeError as jde:
            QMessageBox.critical(dialog, "Invalid JSON", f"Format error in JSON:\n{jde}")

    btn_start.clicked.connect(on_start)
    dialog.exec()


class QSpinButton(QPushButton):
    """Button that spins its text/icon clockwise when clicked."""

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self._rotation_angle = 0.0
        self._animation = None

    @pyqtProperty(float)
    def rotation_angle(self) -> float:
        return self._rotation_angle

    @rotation_angle.setter
    def rotation_angle(self, angle: float) -> None:
        self._rotation_angle = angle
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Draw background and border
        from PyQt6.QtWidgets import QStyleOptionButton, QStyle
        opt = QStyleOptionButton()
        self.initStyleOption(opt)
        text_copy = opt.text
        opt.text = ""
        self.style().drawControl(QStyle.ControlElement.CE_PushButton, opt, painter, self)
        
        # Draw rotated text centered
        painter.save()
        cx = self.width() / 2.0
        cy = self.height() / 2.0
        painter.translate(cx, cy)
        painter.rotate(self._rotation_angle)
        
        painter.setFont(self.font())
        fm = painter.fontMetrics()
        rect = fm.boundingRect(text_copy)
        tx = -rect.width() / 2.0 - rect.x()
        ty = -rect.height() / 2.0 - rect.y()
        
        # Use text color from theme palette
        color = self.palette().color(QPalette.ColorRole.ButtonText)
        painter.setPen(color)
        painter.drawText(int(tx), int(ty), text_copy)
        painter.restore()
        painter.end()

    def trigger_spin(self) -> None:
        if self._animation and self._animation.state() == QPropertyAnimation.State.Running:
            return
        self._animation = QPropertyAnimation(self, b"rotation_angle", self)
        self._animation.setDuration(600)
        self._animation.setStartValue(0.0)
        self._animation.setEndValue(360.0)
        self._animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._animation.start()


class OverlayWindow(QMainWindow):
    answer_ready = pyqtSignal(object)
    status_changed = pyqtSignal(str)
    listening_toggled = pyqtSignal(bool)
    force_coding_requested = pyqtSignal()
    scan_screen_requested = pyqtSignal()
    watch_screen_toggled = pyqtSignal(bool)
    refresh_requested = pyqtSignal()
    assessment_mode_toggled = pyqtSignal(bool)
    capture_assessment_requested = pyqtSignal()
    submit_assessment_requested = pyqtSignal()
    clear_assessment_requested = pyqtSignal()
    logout_requested = pyqtSignal()

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
        self.setMouseTracking(True)
        self._resize_dir = None
        self._resize_start_pos = None
        self._resize_start_geom = None
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

        self._contrast_timer = QTimer(self)
        self._contrast_timer.timeout.connect(self._check_screen_contrast)
        self._contrast_timer.start(2000)

        self._auto_hide_timer = QTimer(self)
        self._auto_hide_timer.timeout.connect(self._on_auto_hide_timeout)

    def _setup_ui(self) -> None:
        self.setWindowTitle("WboxAI")
        
        # Load window icon
        import sys
        from pathlib import Path
        frozen = getattr(sys, "frozen", False)
        if frozen:
            logo_path = Path(sys._MEIPASS) / "wboxai_app" / "logo.png"
        else:
            logo_path = Path(__file__).resolve().parent / "logo.png"
        if logo_path.is_file():
            self.setWindowIcon(QIcon(str(logo_path)))
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
        active_cnt = len(config.get_active_providers())
        min_w = 420 if active_cnt <= 1 else (650 if active_cnt == 2 else 900)
        self.setMinimumSize(min_w, 320)

        default_w = 680 if active_cnt <= 1 else (950 if active_cnt == 2 else 1200)
        self.resize(default_w, 520)

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
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        title = QLabel("WboxAI")
        title.setObjectName("title")
        header.addWidget(title)
        header.addStretch()

        # Group 1: Toggle switches
        self.btn_coding = QToggleSwitch(text="Coding", mini_thumb=True)
        self.btn_coding.setChecked(False)
        self.btn_coding.toggled.connect(self._on_force_coding_click)
        header.addWidget(self.btn_coding)

        self.btn_assessment = QToggleSwitch(text="Assessments", mini_thumb=True)
        self.btn_assessment.setChecked(False)
        self.btn_assessment.toggled.connect(self._on_assessment_toggle)
        header.addWidget(self.btn_assessment)

        self.btn_share_hide = QToggleSwitch(text="Share-Hide")
        self.btn_share_hide.setChecked(config.INVISIBLE_IN_SHARE)
        self.btn_share_hide.toggled.connect(self._on_share_hide_toggle)
        header.addWidget(self.btn_share_hide)

        # Group 2: Regular action text buttons
        self.btn_scan = QPushButton("Scan screen")
        self.btn_scan.setObjectName("primary")
        self.btn_scan.clicked.connect(self._on_scan_button_clicked)

        self.btn_auto_scan = QToggleSwitch(text="Auto")
        self.btn_auto_scan.setFixedHeight(30)
        self.btn_auto_scan.setFixedWidth(64)
        self.btn_auto_scan.setMaximumWidth(0)
        self.btn_auto_scan.hide()
        self.btn_auto_scan.toggled.connect(self._on_auto_scan_toggled)

        scan_layout = QHBoxLayout()
        scan_layout.setContentsMargins(0, 0, 0, 0)
        scan_layout.setSpacing(4)
        scan_layout.addWidget(self.btn_scan)
        scan_layout.addWidget(self.btn_auto_scan)
        header.addLayout(scan_layout)

        self.btn_listen = QPushButton("Start listening")
        self.btn_listen.setObjectName("primary")
        self.btn_listen.clicked.connect(self._on_listen_click)
        header.addWidget(self.btn_listen)

        # Group 3: Utility symbol buttons
        self.btn_refresh = QSpinButton("↻")
        self.btn_refresh.setObjectName("refresh")
        self.btn_refresh.setFixedSize(30, 30)
        self.btn_refresh.setToolTip("Abort and Refresh LLM")
        self.btn_refresh.clicked.connect(self._on_refresh_clicked)
        header.addWidget(self.btn_refresh)

        self.btn_logout = QPushButton("⏻")
        self.btn_logout.setObjectName("logout")
        self.btn_logout.setFixedSize(30, 30)
        self.btn_logout.setToolTip("Logout — return to login screen")
        self.btn_logout.clicked.connect(self._on_logout_clicked)
        header.addWidget(self.btn_logout)

        self.btn_close = QPushButton("✕")
        self.btn_close.setObjectName("close")
        self.btn_close.setFixedSize(30, 30)
        self.btn_close.setToolTip("Exit WboxAI")
        self.btn_close.clicked.connect(self._exit_app)
        header.addWidget(self.btn_close)

        layout.addLayout(header)

        # Assessment sub-bar layout (shown when Assessments toggle is active)
        self.assessment_bar_widget = QWidget()
        as_layout = QHBoxLayout(self.assessment_bar_widget)
        as_layout.setContentsMargins(4, 2, 4, 2)
        as_layout.setSpacing(8)

        as_label = QLabel("Assessment Context:")
        as_label.setStyleSheet("font-weight: bold; color: #60A5FA; font-size: 11px;")
        as_layout.addWidget(as_label)

        self.btn_add_screen = QPushButton("+ Capture Screen")
        self.btn_add_screen.setObjectName("primary")
        self.btn_add_screen.setFixedHeight(26)
        self.btn_add_screen.clicked.connect(self._on_add_assessment_screen)
        as_layout.addWidget(self.btn_add_screen)

        self.btn_submit_assessment = QPushButton("Submit (0)")
        self.btn_submit_assessment.setObjectName("primary")
        self.btn_submit_assessment.setFixedHeight(26)
        self.btn_submit_assessment.setStyleSheet("background-color: #10B981; color: white; font-weight: bold; padding: 2px 12px;")
        self.btn_submit_assessment.clicked.connect(self._on_submit_assessment)
        as_layout.addWidget(self.btn_submit_assessment)

        self.btn_clear_assessment = QPushButton("Clear")
        self.btn_clear_assessment.setFixedHeight(26)
        self.btn_clear_assessment.clicked.connect(self._on_clear_assessment)
        as_layout.addWidget(self.btn_clear_assessment)
        as_layout.addStretch()

        self.assessment_bar_widget.hide()
        layout.addWidget(self.assessment_bar_widget)

        # Opacity slider: 0 = transparent, 100 = solid panel.
        self.blur_slider = QSlider(Qt.Orientation.Horizontal)
        self.blur_slider.setObjectName("blur_slider")
        self.blur_slider.setRange(0, 100)
        self.blur_slider.setValue(int(config.GLASS_PANEL_TINT_PERCENT))
        self.blur_slider.setToolTip("Adjust overlay opacity")
        self.blur_slider.valueChanged.connect(self._on_blur_changed)
        layout.addWidget(self.blur_slider)

        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("status")
        layout.addWidget(self.status_label)

        layout.addWidget(QLabel("Live Transcript", objectName="section"))
        self.live_transcript_box = QTextEdit()
        self.live_transcript_box.setReadOnly(True)
        self.live_transcript_box.setMaximumHeight(64)
        self._make_see_through_edit(self.live_transcript_box)
        layout.addWidget(self.live_transcript_box)

        layout.addWidget(QLabel("Question / problem", objectName="section"))
        self.question_box = QTextEdit()
        self.question_box.setReadOnly(True)
        self.question_box.setMaximumHeight(72)
        self._make_see_through_edit(self.question_box)
        layout.addWidget(self.question_box)

        self.providers_layout = QHBoxLayout()
        self.providers_layout.setContentsMargins(0, 0, 0, 0)
        self.providers_layout.setSpacing(10)
        layout.addLayout(self.providers_layout, stretch=1)

        self.columns = {}
        active = config.get_active_providers()
        if not active:
            no_key_lbl = QLabel(
                "Please configure at least one API key (OPENAI_API_KEY, GEMINI_API_KEY, or CLAUDE_API_KEY) in .env to use the copilot."
            )
            no_key_lbl.setWordWrap(True)
            no_key_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.providers_layout.addWidget(no_key_lbl)
        else:
            for provider in active:
                col_widget = QWidget()
                col_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
                col_layout = QVBoxLayout(col_widget)
                col_layout.setContentsMargins(0, 0, 0, 0)
                col_layout.setSpacing(8)

                header_lbl = QLabel(f"{provider.capitalize()} Answer", objectName="section")
                col_layout.addWidget(header_lbl)

                answer_box = QTextEdit()
                answer_box.setReadOnly(True)
                answer_box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
                self._make_see_through_edit(answer_box)
                col_layout.addWidget(answer_box, stretch=1)

                code_sec = QWidget()
                self._make_translucent_widget(code_sec)
                code_layout = QVBoxLayout(code_sec)
                code_layout.setContentsMargins(0, 0, 0, 0)

                code_header = QHBoxLayout()
                code_header.addWidget(QLabel("Code", objectName="section"))
                code_header.addStretch()

                btn_copy = QPushButton("Copy code")
                btn_copy.setObjectName("primary")
                code_header.addWidget(btn_copy)
                code_layout.addLayout(code_header)

                code_box = QPlainTextEdit()
                code_box.setReadOnly(True)
                self._make_see_through_edit(code_box)
                mono = QFont("Consolas", 16)
                code_box.setFont(mono)
                code_box.setMaximumHeight(200)
                code_layout.addWidget(code_box)

                col_layout.addWidget(code_sec, stretch=0)
                code_sec.hide()

                # Save references before connecting
                self.columns[provider] = {
                    "widget": col_widget,
                    "header": header_lbl,
                    "answer_box": answer_box,
                    "code_section": code_sec,
                    "code_box": code_box,
                    "btn_copy": btn_copy
                }

                # Bind the specific code_box to copy function
                btn_copy.clicked.connect(lambda checked, cb=code_box: self._on_copy_provider_code(cb))

                self.providers_layout.addWidget(col_widget, stretch=1)

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
            widgets = [
                self.findChild(QLabel, "title"),
                self.status_label,
                self.findChild(QLabel, "hint"),
                self.question_box,
            ]
            for col in self.columns.values():
                widgets.append(col["header"])
                widgets.append(col["answer_box"])
                widgets.append(col["code_box"])
            for w in widgets:
                if w is not None:
                    self._apply_text_halo(w)
            for w in central.findChildren(QLabel, "section"):
                self._apply_text_halo(w)
        elif self._transparent:
            widgets = [
                self.findChild(QLabel, "title"),
                self.status_label,
                self.findChild(QLabel, "hint"),
            ]
            for col in self.columns.values():
                widgets.append(col["header"])
            for w in widgets:
                if w is not None:
                    self._apply_text_halo(w)
            for w in central.findChildren(QLabel, "section"):
                self._apply_text_halo(w)
        else:
            self._apply_panel_shadow(central)
        self.setStyleSheet(glass_stylesheet(transparent=self._transparent))
        self.set_text_color_mode(is_light_bg=False)
        QApplication.setFont(QFont("Segoe UI", 14))

        QShortcut(QKeySequence("Ctrl+H"), self, self.hide)
        QShortcut(QKeySequence("Ctrl+Shift+H"), self, self._show_and_exclude)
        QShortcut(QKeySequence("Ctrl+Shift+C"), self, self._shortcut_force_coding)
        QShortcut(QKeySequence("Ctrl+Shift+S"), self, self._on_scan_button_clicked)
        QShortcut(QKeySequence("Escape"), self, self._exit_app)

    def _make_translucent_widget(self, widget: QWidget) -> None:
        if self._transparent:
            widget.setAutoFillBackground(False)

    def _make_see_through_edit(self, edit: QTextEdit | QPlainTextEdit) -> None:
        """Force text areas transparent with a strong text outline/halo so it works on any background."""
        self._make_translucent_widget(edit)
        edit.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        edit.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        edit.viewport().setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        edit.viewport().setAutoFillBackground(False)
        pal = edit.palette()
        pal.setColor(QPalette.ColorRole.Base, QColor(0, 0, 0, 0))
        pal.setColor(QPalette.ColorRole.Text, QColor(255, 255, 255))
        edit.setPalette(pal)
        edit.setStyleSheet(
            "background: transparent; background-color: transparent; border: none; color: #FFFFFF;"
        )
        edit.viewport().setStyleSheet("background: transparent; background-color: transparent;")
        self._apply_text_halo(edit)

    def _apply_stealth_focus(self, central: QWidget) -> None:
        """Hover + wheel scroll without focusing the overlay (keeps coding tab active)."""
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        central.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        boxes = [self.question_box]
        for col in self.columns.values():
            boxes.append(col["answer_box"])
            boxes.append(col["code_box"])

        for box in boxes:
            box.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            box.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        buttons = [
            self.btn_coding,
            self.btn_scan,
            self.btn_auto_scan,
            self.btn_share_hide,
            self.btn_refresh,
            self.btn_logout,
            self.btn_listen,
            self.btn_close,
            self.blur_slider,
        ] + [col["btn_copy"] for col in self.columns.values()]

        for btn in buttons:
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def _scroll_target_at(self, global_pos: QPoint) -> QTextEdit | QPlainTextEdit | None:
        panel = getattr(self, "_central_panel", None)
        if panel is None:
            return None
        local = panel.mapFromGlobal(global_pos)
        
        # 1. Check if inside the question box area
        if self.question_box.geometry().contains(local):
            return self.question_box

        # 2. Check if inside any provider column area
        for provider, col in self.columns.items():
            if col["widget"].geometry().contains(local):
                col_local = col["widget"].mapFrom(panel, local)
                if col["code_section"].isVisible() and col_local.y() > col["widget"].height() * 0.45:
                    return col["code_box"]
                return col["answer_box"]

        # 3. Fallback: if hovering over the overlay window itself (margins, spacing, drag-strip)
        if self.rect().contains(self.mapFromGlobal(global_pos)):
            if self.columns:
                primary = "openai" if "openai" in self.columns else list(self.columns.keys())[0]
                return self.columns[primary]["answer_box"]
            return self.question_box

        return None

    @staticmethod
    def _apply_wheel_scroll(target: QTextEdit | QPlainTextEdit, delta_y: int) -> None:
        bar = target.verticalScrollBar()
        step = max(20, abs(delta_y) // 3)
        bar.setValue(bar.value() - step if delta_y > 0 else bar.value() + step)

    def _handle_hover_wheel(self, global_pos: QPoint, delta_y: int) -> bool:
        target = self._scroll_target_at(global_pos)
        if target is None:
            return False
        self._apply_wheel_scroll(target, delta_y)
        return True

    @staticmethod
    def _scroll_to_bottom(target: QTextEdit | QPlainTextEdit) -> None:
        bar = target.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _set_plain_text_autoscroll(
        self,
        target: QTextEdit | QPlainTextEdit,
        text: str,
    ) -> None:
        target.setPlainText(text)
        self._scroll_to_bottom(target)
        QTimer.singleShot(0, lambda target=target: self._scroll_to_bottom(target))

    @staticmethod
    def _apply_text_halo(widget: QWidget) -> None:
        """Strong black shadow/halo so white copilot text stays readable on any background."""
        fx = QGraphicsDropShadowEffect(widget)
        fx.setBlurRadius(8)
        fx.setOffset(0, 0)
        fx.setColor(QColor(0, 0, 0, 255))
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

        if et == QEvent.Type.Wheel and isinstance(event, QWheelEvent):
            if self._handle_hover_wheel(
                event.globalPosition().toPoint(),
                event.angleDelta().y(),
            ):
                event.accept()
                return True
            return False

        return False

    def wheelEvent(self, event: QWheelEvent) -> None:
        if self._handle_hover_wheel(
            event.globalPosition().toPoint(),
            event.angleDelta().y(),
        ):
            event.accept()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            border = 8
            w = self.width()
            h = self.height()

            left = pos.x() < border
            right = pos.x() > w - border
            top = pos.y() < border
            bottom = pos.y() > h - border

            direction = ""
            if left: direction += "L"
            if right: direction += "R"
            if top: direction += "T"
            if bottom: direction += "B"

            if direction:
                self._resize_dir = direction
                self._resize_start_pos = event.globalPosition().toPoint()
                self._resize_start_geom = self.geometry()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        pos = event.position().toPoint()
        border = 8
        w = self.width()
        h = self.height()

        if not event.buttons() & Qt.MouseButton.LeftButton:
            left = pos.x() < border
            right = pos.x() > w - border
            top = pos.y() < border
            bottom = pos.y() > h - border

            if (left and top) or (right and bottom):
                self.setCursor(Qt.CursorShape.SizeFDiagCursor)
            elif (right and top) or (left and bottom):
                self.setCursor(Qt.CursorShape.SizeBDiagCursor)
            elif left or right:
                self.setCursor(Qt.CursorShape.SizeHorCursor)
            elif top or bottom:
                self.setCursor(Qt.CursorShape.SizeVerCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)
        elif self._resize_dir:
            delta = event.globalPosition().toPoint() - self._resize_start_pos
            geom = QRect(self._resize_start_geom)
            min_w = self.minimumWidth()
            min_h = self.minimumHeight()

            if "L" in self._resize_dir:
                new_w = max(min_w, geom.width() - delta.x())
                geom.setLeft(geom.right() - new_w + 1)
            if "R" in self._resize_dir:
                new_w = max(min_w, geom.width() + delta.x())
                geom.setWidth(new_w)
            if "T" in self._resize_dir:
                new_h = max(min_h, geom.height() - delta.y())
                geom.setTop(geom.bottom() - new_h + 1)
            if "B" in self._resize_dir:
                new_h = max(min_h, geom.height() + delta.y())
                geom.setHeight(new_h)

            self.setGeometry(geom)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._resize_dir = None
        self._resize_start_pos = None
        self._resize_start_geom = None
        super().mouseReleaseEvent(event)

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

    def _on_logout_clicked(self) -> None:
        from PyQt6.QtWidgets import QMessageBox
        reply = QMessageBox.question(
            self,
            "Logout",
            "Are you sure you want to logout?\n\nYou will need to sign in again to use WboxAI.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.logout_requested.emit()

    def _on_configure_clicked(self) -> None:
        from installer import SetupWizard
        
        # Temporarily enable focus on main window so setup wizard works perfectly
        old_flags = self.windowFlags()
        if config.STEALTH_FOCUS:
            self.setWindowFlags(old_flags & ~Qt.WindowType.WindowDoesNotAcceptFocus)
            self.show()
            
        self.wizard = SetupWizard(config_only=True)
        self.wizard.setWindowFlags(self.wizard.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        
        def on_wizard_closed():
            if config.STEALTH_FOCUS:
                self.setWindowFlags(old_flags)
                self.show()
            self.schedule_exclude()
            
        self.wizard.closed.connect(on_wizard_closed)
        self.wizard.show()

    def _on_refresh_clicked(self) -> None:
        self.btn_refresh.trigger_spin()
        self.refresh_requested.emit()
        self.schedule_exclude()

    def update_live_transcript(self, role: str, text: str, is_final: bool = True) -> None:
        role_formatted = role.strip().capitalize() if role else "Unknown"
        if not is_final:
            line = f"[{role_formatted} speaking...] {text}"
        else:
            line = f"[{role_formatted}] {text}"
        
        current = self.live_transcript_box.toPlainText().strip()
        if is_final:
            new_content = f"{current}\n{line}".strip() if current else line
            lines = new_content.splitlines()[-10:]
            self._set_plain_text_autoscroll(self.live_transcript_box, "\n".join(lines))
        else:
            lines = current.splitlines()[-8:] if current else []
            display = "\n".join(lines + [line]).strip()
            self.live_transcript_box.setPlainText(display)
            self._scroll_to_bottom(self.live_transcript_box)

    def clear_responses(self) -> None:
        self._last_question = ""
        self.question_box.clear()
        self.live_transcript_box.clear()
        if hasattr(self, "_last_responses"):
            self._last_responses.clear()
        for provider, col in self.columns.items():
            col["answer_box"].clear()
            col["code_box"].clear()
            col["code_section"].hide()
            col["header"].setText(f"{provider.capitalize()} Answer")
        self.apply_normal_layout()
        self.schedule_exclude()

    def _on_listen_click(self) -> None:
        self._listening = not self._listening
        self.btn_listen.setText("Stop listening" if self._listening else "Start listening")
        self.listening_toggled.emit(self._listening)
        self.schedule_exclude()

    def _on_force_coding_click(self, *args) -> None:
        self._update_all_responses_layout()
        self.force_coding_requested.emit()
        self.schedule_exclude()

    def set_coding_busy(self, busy: bool) -> None:
        self.btn_coding.setEnabled(not busy)

    def _on_blur_changed(self, val: int) -> None:
        opacity = max(0.0, min(100.0, float(val)))
        config.GLASS_PANEL_TINT_PERCENT = opacity
        config.GLASS_SEE_THROUGH = opacity <= 1.0
        config.GLASS_BLUR_PERCENT = min(24.0, opacity * 0.24)
        self.setStyleSheet(glass_stylesheet(transparent=self._transparent))
        self.set_text_color_mode(is_light_bg=opacity >= 55.0)
        apply_glass_backdrop(self, config.GLASS_BLUR_PERCENT)
        self._drag_strip.update()
        self.schedule_exclude()

    def _on_scan_button_clicked(self) -> None:
        if self.btn_assessment.isChecked():
            self.capture_assessment_requested.emit()
        else:
            self.scan_screen_requested.emit()
            self._animate_auto_scan(True)
            self._auto_hide_timer.start(10000) # Show for 10 seconds
        self.schedule_exclude()

    def _on_assessment_toggle(self, checked: bool) -> None:
        if checked:
            self.btn_coding.setChecked(True)
            self.assessment_bar_widget.show()
            self.status_label.setText("Assessment Mode active: Capture screenshots then click Submit.")
        else:
            self.assessment_bar_widget.hide()
            self.status_label.setText("Ready")
        self.assessment_mode_toggled.emit(checked)
        self.schedule_exclude()

    def update_assessment_count(self, count: int) -> None:
        self.btn_submit_assessment.setText(f"Submit ({count})")
        if count == 0:
            self.status_label.setText("Assessment Mode: 0 screenshots queued. Click '+ Capture Screen' or 'Scan screen'.")
        else:
            self.status_label.setText(f"Assessment Mode: {count} screenshot(s) queued. Click Submit when ready.")
        self.schedule_exclude()

    def _on_add_assessment_screen(self) -> None:
        self.capture_assessment_requested.emit()

    def _on_submit_assessment(self) -> None:
        self.submit_assessment_requested.emit()

    def _on_clear_assessment(self) -> None:
        self.clear_assessment_requested.emit()

    def _on_auto_scan_toggled(self, checked: bool) -> None:
        self.watch_screen_toggled.emit(checked)
        if checked:
            self._auto_hide_timer.stop() # Keep it open
        else:
            self._animate_auto_scan(False) # Slide back in
        self.schedule_exclude()

    def _on_auto_hide_timeout(self) -> None:
        self._auto_hide_timer.stop()
        if not self.btn_auto_scan.isChecked():
            self._animate_auto_scan(False)

    def _animate_auto_scan(self, show: bool) -> None:
        if show:
            self.btn_auto_scan.show()
            self._auto_scan_anim = QPropertyAnimation(self.btn_auto_scan, b"maximumWidth")
            self._auto_scan_anim.setDuration(250)
            self._auto_scan_anim.setStartValue(self.btn_auto_scan.maximumWidth())
            self._auto_scan_anim.setEndValue(64)
            self._auto_scan_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            self._auto_scan_anim.start()
        else:
            self._auto_scan_anim = QPropertyAnimation(self.btn_auto_scan, b"maximumWidth")
            self._auto_scan_anim.setDuration(250)
            self._auto_scan_anim.setStartValue(self.btn_auto_scan.width())
            self._auto_scan_anim.setEndValue(0)
            self._auto_scan_anim.setEasingCurve(QEasingCurve.Type.InCubic)
            self._auto_scan_anim.finished.connect(self.btn_auto_scan.hide)
            self._auto_scan_anim.start()

    def _on_share_hide_toggle(self, checked: bool) -> None:
        config.INVISIBLE_IN_SHARE = checked
        if checked:
            ok, note = apply_to_window(self)
            self._share_hide_ok = ok
            if note:
                self.status_label.setText(note)
        else:
            from capture_exclude import restore_window
            ok, note = restore_window(self)
            if note:
                self.status_label.setText(note)
        self.schedule_exclude()

    def _on_copy_provider_code(self, code_box) -> None:
        code = code_box.toPlainText().strip()
        if code:
            QGuiApplication.clipboard().setText(code)
            self.status_label.setText("Code copied")
        self.schedule_exclude()

    def _shortcut_force_coding(self) -> None:
        self.btn_coding.setChecked(not self.btn_coding.isChecked())

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
        
        num_cols = len(self.columns)
        if num_cols == 3:
            width = min(1200, max(900, int(avail.width() * 0.6)))
        elif num_cols == 2:
            width = min(900, max(680, int(avail.width() * 0.45)))
        else:
            width = min(500, max(360, int(avail.width() * 0.34)))

        self.setGeometry(
            avail.x() + margin,
            avail.y() + margin,
            width,
            avail.height() - 2 * margin,
        )
        self.question_box.setMaximumHeight(56)
        for col in self.columns.values():
            col["code_box"].setMaximumHeight(16_777_215)

    def apply_normal_layout(self) -> None:
        """Restore compact window after behavioral / non-coding answers."""
        if self._layout_mode == "coding":
            if self._saved_normal_geometry is not None:
                self.setGeometry(self._saved_normal_geometry)
            else:
                num_cols = len(self.columns)
                normal_w = 680 if num_cols <= 1 else (950 if num_cols == 2 else 1200)
                self.resize(normal_w, 520)
                self.move(80, 80)
        self._layout_mode = "normal"
        self.question_box.setMaximumHeight(72)
        for col in self.columns.values():
            col["code_box"].setMaximumHeight(self._code_box_max_default)

    def _update_all_responses_layout(self) -> None:
        is_coding_active = self.btn_coding.isChecked()
        is_assessment_active = self.btn_assessment.isChecked()
        has_any_code_layout = False
        
        for provider, col in self.columns.items():
            if is_assessment_active:
                col["code_section"].show()
                col["answer_box"].hide()
                col["header"].setText(f"{provider.capitalize()} Code")
                
                response = None
                if hasattr(self, "_last_responses") and self._last_responses and provider in self._last_responses:
                    response = self._last_responses[provider].get("response")
                
                if response:
                    code_text = response.code or ""
                    if not code_text or code_text.strip().upper() == "N/A":
                        code_text = f"// Generating assessment code solution... Please wait..."
                    self._set_plain_text_autoscroll(col["code_box"], code_text)
                else:
                    self._set_plain_text_autoscroll(col["code_box"], "// Ready for assessment screenshots submission")
                has_any_code_layout = True
            elif is_coding_active:
                col["code_section"].show()
                col["answer_box"].show()
                col["header"].setText(f"{provider.capitalize()} (Approach)")
                
                response = None
                if hasattr(self, "_last_responses") and self._last_responses and provider in self._last_responses:
                    response = self._last_responses[provider].get("response")
                
                if response:
                    self._set_plain_text_autoscroll(col["answer_box"], response.approach or response.full_text)
                    code_text = response.code or ""
                    if not code_text or code_text.strip().upper() == "N/A":
                        code_text = f"// Generating coding solution for '{self.question_box.toPlainText()[:40]}...' - Please wait..."
                    self._set_plain_text_autoscroll(col["code_box"], code_text)
                else:
                    self._set_plain_text_autoscroll(col["answer_box"], "")
                    self._set_plain_text_autoscroll(col["code_box"], "// Ready for coding problem")
                has_any_code_layout = True
            else:
                col["code_section"].hide()
                col["answer_box"].show()
                col["header"].setText(f"{provider.capitalize()} Answer")
                
                response = None
                if hasattr(self, "_last_responses") and self._last_responses and provider in self._last_responses:
                    response = self._last_responses[provider].get("response")
                
                if response:
                    full_content = response.approach or response.full_text
                    if response.code and response.code.strip().upper() != "N/A":
                        if "```" not in full_content:
                            full_content += f"\n\nCode:\n```{config.CODE_LANGUAGE}\n{response.code}\n```"
                    self._set_plain_text_autoscroll(col["answer_box"], full_content)
                else:
                    self._set_plain_text_autoscroll(col["answer_box"], "")
                    self._set_plain_text_autoscroll(col["code_box"], "")
                
        if has_any_code_layout:
            self.apply_coding_layout()
        else:
            self.apply_normal_layout()
        self.schedule_exclude()

    def _set_response(self, data: dict) -> None:
        if not isinstance(data, dict):
            return
        provider = data.get("provider")
        if provider not in self.columns:
            return

        if not hasattr(self, "_last_responses"):
            self._last_responses = {}
        self._last_responses[provider] = data

        self._update_all_responses_layout()

    def set_watch_checked(self, checked: bool) -> None:
        self.btn_auto_scan.setChecked(checked)
        if checked:
            self._animate_auto_scan(True)
            self._auto_hide_timer.stop()
        else:
            self._animate_auto_scan(False)

    def set_question(self, text: str) -> None:
        self._last_question = text
        self._set_plain_text_autoscroll(self.question_box, text)
        for col in self.columns.values():
            if not self.btn_coding.isChecked() and not self.btn_assessment.isChecked():
                self._set_plain_text_autoscroll(col["answer_box"], "Generating...")

    def get_last_question(self) -> str:
        return self._last_question

    def _check_screen_contrast(self) -> None:
        """Lightweight background contrast sampler that updates text color mode dynamically."""
        try:
            screen = QGuiApplication.primaryScreen()
            if not screen:
                return

            geom = self.geometry()
            pixmap = screen.grabWindow(0, geom.x(), geom.y(), geom.width(), geom.height())
            image = pixmap.toImage()

            brightness_sum = 0.0
            count = 0
            step_x = max(1, geom.width() // 10)
            step_y = max(1, geom.height() // 10)
            for x in range(0, geom.width(), step_x):
                for y in range(0, geom.height(), step_y):
                    color = image.pixelColor(x, y)
                    luminance = 0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue()
                    brightness_sum += luminance
                    count += 1

            if count > 0:
                avg = brightness_sum / count
                self.set_text_color_mode(is_light_bg=(avg > 140))
        except Exception:
            pass

    def set_text_color_mode(self, is_light_bg: bool) -> None:
        """Dynamically update the text color and black/white shadow outlines."""
        color_str = "#000000" if is_light_bg else "#FFFFFF"
        shadow_color = QColor(255, 255, 255, 255) if is_light_bg else QColor(0, 0, 0, 255)

        boxes = [self.question_box]
        for col in self.columns.values():
            boxes.append(col["answer_box"])
            boxes.append(col["code_box"])

        tint = max(0.0, min(100.0, float(config.GLASS_PANEL_TINT_PERCENT)))
        box_alpha = 0 if tint <= 3.0 else max(1, min(255, int(255 * min(100.0, tint * 0.4) / 100.0)))
        box_bg = "transparent" if box_alpha == 0 else f"rgba(255, 255, 255, {box_alpha})"
        for box in boxes:
            box.setStyleSheet(
                f"background: {box_bg}; background-color: {box_bg}; border: none; color: {color_str};"
            )
            box.viewport().setStyleSheet(
                f"background: {box_bg}; background-color: {box_bg};"
            )
            fx = box.graphicsEffect()
            if isinstance(fx, QGraphicsDropShadowEffect):
                fx.setColor(shadow_color)

        for lbl in self.findChildren(QLabel):
            obj_name = lbl.objectName()
            if obj_name in ("title", "section", "hint", "drag_grip", "status") or isinstance(lbl, QLabel):
                if obj_name:
                    lbl.setStyleSheet(f"#{obj_name} {{ background: transparent; color: {color_str}; }}")
                else:
                    lbl.setStyleSheet(f"background: transparent; color: {color_str};")
                fx = lbl.graphicsEffect()
                if isinstance(fx, QGraphicsDropShadowEffect):
                    fx.setColor(shadow_color)

        # Update QToggleSwitch contrast settings
        for sw in self.findChildren(QToggleSwitch):
            sw.set_light_mode(is_light_bg)

        # Update buttons styling based on contrast
        if is_light_bg:
            btn_primary_style = """
                QPushButton#primary, QToolButton#primary {
                    background-color: rgba(0, 0, 0, 180);
                    color: #FFFFFF;
                    border: 1px solid rgba(0, 0, 0, 60);
                    height: 30px;
                    border-radius: 15px;
                    padding: 0px 16px;
                    margin: 0px;
                    font-size: 12px;
                    font-weight: normal;
                }
                QPushButton#primary:hover, QToolButton#primary:hover {
                    background-color: rgba(0, 0, 0, 225);
                }
            """
            btn_refresh_style = """
                QPushButton#refresh {
                    background-color: rgba(0, 0, 0, 180);
                    color: #FFFFFF;
                    border: 1px solid rgba(0, 0, 0, 60);
                    height: 30px;
                    width: 30px;
                    border-radius: 15px;
                    font-size: 17px;
                    font-weight: normal;
                    padding: 0;
                    margin: 0px;
                }
                QPushButton#refresh:hover {
                    background-color: rgba(0, 0, 0, 225);
                }
            """
            btn_close_style = """
                QPushButton#close {
                    background: transparent;
                    color: #000000;
                    border: none;
                    height: 30px;
                    width: 30px;
                    border-radius: 15px;
                    font-size: 17px;
                    font-weight: normal;
                    padding: 0;
                    margin: 0px;
                }
                QPushButton#close:hover {
                    background-color: rgba(0, 0, 0, 25);
                }
            """
            slider_style = """
                QSlider#blur_slider::groove:horizontal {
                    background: rgba(0, 0, 0, 30);
                }
                QSlider#blur_slider::sub-page:horizontal {
                    background: rgba(0, 0, 0, 100);
                }
                QSlider#blur_slider::handle:horizontal {
                    background: #000000;
                }
            """
        else:
            btn_primary_style = """
                QPushButton#primary, QToolButton#primary {
                    background-color: rgba(0, 0, 0, 120);
                    color: rgba(255, 255, 255, 250);
                    border: 1px solid rgba(255, 255, 255, 45);
                    height: 30px;
                    border-radius: 15px;
                    padding: 0px 16px;
                    margin: 0px;
                    font-size: 12px;
                    font-weight: normal;
                }
                QPushButton#primary:hover, QToolButton#primary:hover {
                    background-color: rgba(0, 0, 0, 160);
                }
            """
            btn_refresh_style = """
                QPushButton#refresh {
                    background-color: rgba(0, 0, 0, 90);
                    color: rgba(255, 255, 255, 250);
                    border: 1px solid rgba(255, 255, 255, 45);
                    height: 30px;
                    width: 30px;
                    border-radius: 15px;
                    font-size: 17px;
                    font-weight: normal;
                    padding: 0;
                    margin: 0px;
                }
                QPushButton#refresh:hover {
                    background-color: rgba(0, 0, 0, 140);
                }
            """
            btn_close_style = """
                QPushButton#close {
                    background: transparent;
                    color: rgba(255, 255, 255, 250);
                    border: none;
                    height: 30px;
                    width: 30px;
                    border-radius: 15px;
                    font-size: 17px;
                    font-weight: normal;
                    padding: 0;
                    margin: 0px;
                }
                QPushButton#close:hover {
                    background-color: rgba(255, 255, 255, 25);
                }
            """
            slider_style = """
                QSlider#blur_slider::groove:horizontal {
                    background: rgba(255, 255, 255, 30);
                }
                QSlider#blur_slider::sub-page:horizontal {
                    background: rgba(255, 255, 255, 100);
                }
                QSlider#blur_slider::handle:horizontal {
                    background: #FFFFFF;
                }
            """

        for btn in self.findChildren(QPushButton):
            obj_name = btn.objectName()
            if obj_name == "primary":
                btn.setStyleSheet(btn_primary_style)
            elif obj_name == "refresh":
                btn.setStyleSheet(btn_refresh_style)
            elif obj_name == "close":
                btn.setStyleSheet(btn_close_style)
            elif obj_name == "logout":
                # Logout button stays consistently red-tinted regardless of bg mode
                btn.setStyleSheet("""
                    QPushButton#logout {
                        background: transparent;
                        color: rgba(248, 113, 113, 200);
                        border: none;
                        height: 30px;
                        width: 30px;
                        border-radius: 15px;
                        font-size: 16px;
                        font-weight: normal;
                        padding: 0;
                        margin: 0px;
                    }
                    QPushButton#logout:hover {
                        background-color: rgba(239, 68, 68, 35);
                        color: rgba(252, 165, 165, 240);
                    }
                """)

        if hasattr(self, "blur_slider"):
            self.blur_slider.setStyleSheet(slider_style)

    # Back-compat for main.py
    def ensure_invisible_to_share(self) -> None:
        self.schedule_exclude()
