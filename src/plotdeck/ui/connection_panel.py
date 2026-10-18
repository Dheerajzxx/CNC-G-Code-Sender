"""Connection controls shown in the main toolbar."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QToolButton,
    QWidget,
)

from ..core.controller import MachineController


class ConnectionPanel(QWidget):
    connectRequested = Signal(str, int, bool)
    disconnectRequested = Signal()

    def __init__(self, parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self.setObjectName("Panel")
        self._connected = False
        self._connecting = False

        self._port = QComboBox()
        self._port.setMinimumWidth(200)
        self._port.setToolTip("Serial port")
        refresh = QToolButton()
        refresh.setText("⟳")
        refresh.setToolTip("Refresh ports")
        refresh.clicked.connect(self.refresh_ports)

        self._baud = QComboBox()
        self._baud.setEditable(True)
        for baud in ("9600", "57600", "115200", "230400", "250000"):
            self._baud.addItem(baud)
        self._baud.setCurrentText("115200")
        self._baud.setFixedWidth(90)
        self._baud.setToolTip("Baud rate")

        self._connect = QPushButton("Connect")
        self._connect.setObjectName("Primary")
        self._connect.setMinimumWidth(96)
        self._connect.clicked.connect(self.toggle)

        demo = QToolButton()
        demo.setText("Demo")
        demo.setToolTip("Connect to a simulated GRBL machine (no hardware)")
        demo.clicked.connect(self._demo)

        self._status = QLabel("")
        self._status.setObjectName("Muted")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        layout.addWidget(QLabel("Port"))
        layout.addWidget(self._port)
        layout.addWidget(refresh)
        layout.addWidget(QLabel("Baud"))
        layout.addWidget(self._baud)
        layout.addWidget(self._connect)
        layout.addWidget(demo)
        layout.addWidget(self._status)

        self.refresh_ports()

    def refresh_ports(self) -> None:
        current = self._port.currentData()
        self._port.clear()
        ports = MachineController.available_ports()
        for device, description in ports:
            label = device if description == device else f"{device}  ·  {description}"
            self._port.addItem(label, device)
        if not ports:
            self._port.addItem("No USB serial ports found", "")
        if current:
            index = self._port.findData(current)
            if index >= 0:
                self._port.setCurrentIndex(index)

    def select_port(self, port: str) -> None:
        if not port:
            return
        index = self._port.findData(port)
        if index >= 0:
            self._port.setCurrentIndex(index)
        elif port.upper() != "DEMO":
            self._port.insertItem(0, port, port)
            self._port.setCurrentIndex(0)

    def baud(self) -> int:
        try:
            return int(self._baud.currentText())
        except ValueError:
            return 115200

    def set_baud(self, baud: int) -> None:
        self._baud.setCurrentText(str(baud))

    def toggle(self) -> None:
        if self._connected:
            self._connecting = True
            self._connect.setEnabled(False)
            self._connect.setText("Disconnecting…")
            self.disconnectRequested.emit()
            return
        port = self._port.currentData()
        if not port:
            self._status.setText("No port selected")
            return
        self._connecting = True
        self._connect.setEnabled(False)
        self._connect.setText("Connecting…")
        self.connectRequested.emit(port, self.baud(), False)

    def _demo(self) -> None:
        self._connecting = True
        self._connect.setEnabled(False)
        self._connect.setText("Connecting…")
        self.connectRequested.emit("DEMO", self.baud(), True)

    def set_connected(self, connected: bool, port: str = "") -> None:
        self._connected = connected
        self._connecting = False
        self._connect.setEnabled(True)
        self._connect.setText("Disconnect" if connected else "Connect")
        self._status.setText(port if connected else "")
        self._port.setEnabled(not connected)
        self._baud.setEnabled(not connected)

    def set_error(self, message: str) -> None:
        self._connecting = False
        self._connect.setEnabled(True)
        self._connect.setText("Connect")
        self._status.setText(message)
