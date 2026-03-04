"""
Компонент для всплывающих уведомлений (Toast notifications)
Минималистичный дизайн в стиле приложения
"""

from PyQt6.QtWidgets import QWidget, QLabel, QHBoxLayout, QVBoxLayout
from PyQt6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QPoint, pyqtProperty
from PyQt6.QtGui import QPainter, QColor, QFont


class ToastNotification(QWidget):
    """Всплывающее уведомление в стиле Toast"""
    
    def __init__(self, parent=None, message="", notification_type="info", duration=3000):
        super().__init__(parent)
        self.message = message
        self.notification_type = notification_type  # "info", "success", "warning", "error"
        self.duration = duration
        self._opacity = 1.0
        
        self.setup_ui()
        self.setup_animation()
        
    def setup_ui(self):
        """Настройка интерфейса уведомления"""
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        # Цвета в зависимости от типа
        colors = {
            "info": {"bg": "#1a1a1a", "text": "#ffffff", "border": "#000000"},
            "success": {"bg": "#10b981", "text": "#ffffff", "border": "#059669"},
            "warning": {"bg": "#f59e0b", "text": "#ffffff", "border": "#d97706"},
            "error": {"bg": "#ef4444", "text": "#ffffff", "border": "#dc2626"}
        }
        
        color = colors.get(self.notification_type, colors["info"])
        
        # Фиксированная ширина тоста для ровного вида всех уведомлений
        self.TOAST_WIDTH = 340
        self.TOAST_MIN_HEIGHT = 44

        # Основной контейнер
        container = QWidget()
        container.setMinimumWidth(self.TOAST_WIDTH)
        container.setStyleSheet(f"""
            QWidget {{
                background-color: {color["bg"]};
                border: 1px solid {color["border"]};
                border-radius: 8px;
                padding: 12px 16px;
            }}
        """)
        
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        
        # Индикатор (цветная точка)
        indicator = QWidget()
        indicator.setFixedSize(8, 8)
        indicator.setStyleSheet(f"""
            QWidget {{
                background-color: {color["text"]};
                border-radius: 4px;
            }}
        """)
        layout.addWidget(indicator)
        
        # Текст сообщения (фиксированная ширина для переноса и ровного блока)
        message_label = QLabel(self.message)
        message_label.setMinimumWidth(self.TOAST_WIDTH - 60)  # минус индикатор и отступы
        message_label.setMaximumWidth(self.TOAST_WIDTH - 60)
        message_label.setStyleSheet(f"""
            QLabel {{
                color: {color["text"]};
                font-size: 13px;
                font-weight: 500;
                background-color: transparent;
                border: none;
            }}
        """)
        message_label.setWordWrap(True)
        layout.addWidget(message_label, 1)
        
        # Главный layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(container)
        
        # Фиксированная ширина и минимальная высота для ровных уведомлений
        self.setFixedWidth(self.TOAST_WIDTH)
        self.setMinimumHeight(self.TOAST_MIN_HEIGHT)
        self.adjustSize()
        
    def setup_animation(self):
        """Настройка анимации появления и исчезновения"""
        self.animation = QPropertyAnimation(self, b"opacity")
        self.animation.setDuration(300)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        
    def showEvent(self, event):
        """Анимация появления"""
        super().showEvent(event)
        self.animation.setStartValue(0.0)
        self.animation.setEndValue(1.0)
        self.animation.start()
        
        # Автоматическое закрытие
        QTimer.singleShot(self.duration, self.fade_out)
        
    def fade_out(self):
        """Анимация исчезновения"""
        try:
            self.animation.finished.disconnect()
        except TypeError:
            pass
        self.animation.setStartValue(1.0)
        self.animation.setEndValue(0.0)
        self.animation.finished.connect(self.close)
        self.animation.start()
        
    def get_opacity(self):
        """Получить прозрачность"""
        return self._opacity
        
    def set_opacity(self, value):
        """Установить прозрачность"""
        self._opacity = value
        self.setWindowOpacity(value)
        
    opacity = pyqtProperty(float, get_opacity, set_opacity)


class ToastManager:
    """Менеджер для управления всплывающими уведомлениями"""
    
    def __init__(self, parent_widget):
        self.parent = parent_widget
        self.notifications = []
        self.spacing = 10
        
    def show(self, message, notification_type="info", duration=3000):
        """Показать уведомление"""
        toast = ToastNotification(self.parent, message, notification_type, duration)
        
        # Позиционируем в правом верхнем углу главного окна (глобальные координаты)
        top_left = self.parent.mapToGlobal(self.parent.rect().topLeft())
        x = top_left.x() + self.parent.width() - toast.width() - 20
        y = top_left.y() + 20 + len(self.notifications) * (toast.height() + self.spacing)
        toast.move(x, y)
        toast.show()
        
        self.notifications.append(toast)
        
        # Безопасно удаляем из списка после закрытия
        def on_toast_destroyed():
            if toast in self.notifications:
                self.notifications.remove(toast)
        toast.destroyed.connect(on_toast_destroyed)
        
        return toast
        
    def show_success(self, message, duration=3000):
        """Показать уведомление об успехе"""
        return self.show(message, "success", duration)
        
    def show_error(self, message, duration=4000):
        """Показать уведомление об ошибке"""
        return self.show(message, "error", duration)
        
    def show_warning(self, message, duration=3500):
        """Показать предупреждение"""
        return self.show(message, "warning", duration)
        
    def show_info(self, message, duration=3000):
        """Показать информационное уведомление"""
        return self.show(message, "info", duration)

