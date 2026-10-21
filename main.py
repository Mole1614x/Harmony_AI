
import sys

from PySide6.QtWidgets import QApplication

from ui.online_main_window import OnlineMainWindow


def main():
    app = QApplication(sys.argv)

    window = OnlineMainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
