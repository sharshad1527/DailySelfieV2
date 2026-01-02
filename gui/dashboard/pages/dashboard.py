# gui/dashboard/pages/dashboard.py
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QWidget, QLabel, QVBoxLayout, QHBoxLayout
from gui.theme.theme_vars import theme_vars

class RecentSelfieCarouselPlaceholder(QFrame):
    """
    Placeholder for recent selfie carousel (horizontal list).
    """
    def __init__(self):
        super().__init__()

        vars = theme_vars()

        self.setObjectName("RecentSelfieCarousel")
        self.setFixedHeight(120)

        self.setStyleSheet(f"""
            QFrame#RecentSelfieCarousel {{
                background-color: {vars['surface_container_high']};
                border-radius: 12px;
            }}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)

        label = QLabel("Recent Selfies (Carousel)")
        label.setAlignment(Qt.AlignCenter)

        layout.addWidget(label)


class TodaySelfieCard(QFrame):
    """
    Primary dashboard card showing today's selfie state.
    """
    def __init__(self):
        super().__init__()
        vars = theme_vars()

        self.setObjectName("TodaySelfieCard")
        self.setMinimumHeight(180)

        # The Rounded Conrer + Theme Color
        self.setStyleSheet(f"""
            QFrame#TodaySelfieCard {{
                background-color: {vars['surface_container_high']};
                border-radius: 16px;
            }}
        """)

        # The Layout for the TodaySelfieCard Act As Root Layout
        layout = QVBoxLayout(self)
        placeholder = QLabel("TodaySelfieCard")
        
        layout.addWidget(placeholder, alignment=Qt.AlignCenter)

        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

    def set_empty_state(self):
        """
        Configure card UI for 'no selfie taken today'.
        """
        pass


    def set_taken_state(self, summary):
        """
        Configure card UI for 'selfie already taken today'.
        """
        pass

class StreakSummaryWidget(QFrame):
    """
    Read-only summary showing current and longest streak.
    """
    def __init__(self):
        super().__init__()

        vars = theme_vars()

        self.setObjectName("StreakSummaryWidget")
        self.setMinimumHeight(90)

        self.setStyleSheet(f"""
            QFrame#StreakSummaryWidget {{
                background-color: {vars['surface_container_high']};
                border-radius: 16px;
            }}
        """)

        layout = QVBoxLayout(self)
        title = QLabel("Streak")
        value = QLabel("0 days")

        layout.addWidget(title)
        layout.addWidget(value)

        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)


class MoodSummaryWidget(QFrame):
    """
    Widget showing mood summary.
    """
    def __init__(self):
        super().__init__()

        vars = theme_vars()

        self.setObjectName("MoodSummaryWidget")
        self.setMinimumHeight(90)

        self.setStyleSheet(f"""
            QFrame#MoodSummaryWidget {{
                background-color: {vars['surface_container_high']};
                border-radius: 16px;
            }}
        """)

        layout = QVBoxLayout(self)

        title = QLabel("Mood (last 30 days)")
        value = QLabel("—")

        layout.addWidget(title)
        layout.addWidget(value)

        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)



class DashboardSurface(QFrame):
    """
    Primary dashboard surface containing today's selfie card and summary widgets.
    """
    def __init__(self):
        super().__init__()
        vars = theme_vars()

        self.setObjectName("DashboardSurface")

        # The Rounded Conrer + Theme Color
        self.setStyleSheet(f"""
            QFrame#DashboardSurface {{
                background-color: {vars['surface_container']};
                border-radius: 12px;
            }}
        """)
        

        # The Layout for the Dashboard Act As Root Layout
        surface_layout = QVBoxLayout(self)

        surface_layout.setContentsMargins(12, 12, 12, 12)
        surface_layout.setSpacing(12)

        # Top Section Contains TodaySelfieCard, And HBox Layout
        top_section = QHBoxLayout()

        today_selfie_card = TodaySelfieCard()

        # Side Column Contains StreakSummaryWidget, MoodSummaryWidget
        side_column = QVBoxLayout()
        side_column.setSpacing(12)

        streak_summary_widget = StreakSummaryWidget()
        mood_summary_widget = MoodSummaryWidget()

        side_column.addWidget(streak_summary_widget)
        side_column.addWidget(mood_summary_widget)

        top_section.addWidget(today_selfie_card, stretch=1)
        top_section.addLayout(side_column, stretch=0)

        surface_layout.addLayout(top_section)
        
        carousel = RecentSelfieCarouselPlaceholder()
        surface_layout.addWidget(carousel)


class DashboardPage(QWidget):
    def __init__(self):
        super().__init__()
        vars = theme_vars()
        
        
                


        root_layout = QVBoxLayout()
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(12)
        surface = DashboardSurface()
        root_layout.addWidget(surface)

        self.setLayout(root_layout)


