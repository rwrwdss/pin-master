"""
Компонент для динамических индикаторов статуса с цветными точками
"""

from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPainter, QColor, QFont


class StatusIndicator(QWidget):
    """Виджет индикатора статуса с цветной точкой"""
    
    def __init__(self, parent=None, text="", status="offline"):
        super().__init__(parent)
        self.text = text
        self.status = status  # "online", "offline", "warning", "error"
        self.setup_ui()
        
    def setup_ui(self):
        """Настройка интерфейса"""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        
        # Цветная точка
        self.dot = QWidget()
        self.dot.setFixedSize(8, 8)
        self.update_status(self.status)
        layout.addWidget(self.dot)
        
        # Текст
        self.label = QLabel(self.text)
        self.label.setStyleSheet("""
            QLabel {
                color: #1a1a1a;
                font-size: 11px;
                font-weight: 500;
                background-color: transparent;
                border: none;
            }
        """)
        layout.addWidget(self.label)
        
        layout.addStretch()
        
    def update_status(self, status):
        """Обновить статус индикатора"""
        self.status = status
        
        colors = {
            "online": "#10b981",      # Зеленый
            "offline": "#9ca3af",     # Серый
            "warning": "#f59e0b",      # Оранжевый
            "error": "#ef4444",        # Красный
            "loading": "#3b82f6"       # Синий
        }
        
        color = colors.get(status, colors["offline"])
        
        self.dot.setStyleSheet(f"""
            QWidget {{
                background-color: {color};
                border-radius: 4px;
            }}
        """)
        
    def set_text(self, text):
        """Установить текст"""
        self.text = text
        self.label.setText(text)
        
    def paintEvent(self, event):
        """Переопределяем для корректной отрисовки"""
        super().paintEvent(event)

