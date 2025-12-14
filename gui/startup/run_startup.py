import sys
from PySide6.QtWidgets import QApplication

from startup.startup_window import StartupWindow


def main():
    app = QApplication(sys.argv)
    win = StartupWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
