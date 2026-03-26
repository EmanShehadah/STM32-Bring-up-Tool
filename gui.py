import sys
import os

from backend import (
    flash_stm32_firmware,
    create_log_filename,
    SerialLoggerWorker,
    FlashWorker,
)
from PySide6.QtCore import QThread, QSettings, Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QLabel,
    QVBoxLayout,
    QLineEdit,
    QPushButton,
    QMessageBox,
    QFrame,
    QFileDialog,
    QHBoxLayout,
)


def open_log_file():
    """Open the logs folder, creating it first if needed."""
    os.makedirs("logs", exist_ok=True)
    os.startfile("logs")


def create_section_frame(title_text):
    """Create a styled section frame with a title label."""
    frame = QFrame()
    frame.setObjectName("sectionFrame")

    layout = QVBoxLayout(frame)
    layout.setContentsMargins(20, 20, 20, 20)
    layout.setSpacing(12)

    title = QLabel(title_text)
    title.setObjectName("sectionTitle")

    layout.addWidget(title, alignment=Qt.AlignLeft)

    return frame, layout


def make_label_and_layout(label_text, placeholder_text):
    """Create a label and line edit stacked vertically."""
    label = QLabel(label_text)
    label_line_edit = QLineEdit()
    label_line_edit.setPlaceholderText(placeholder_text)

    layout = QVBoxLayout()
    layout.addWidget(label)
    layout.addWidget(label_line_edit)

    return label_line_edit, layout


def make_label_and_browse_layout(label_text, placeholder_text, browse_callback):
    """Create a label, line edit, and browse button row."""
    label = QLabel(label_text)

    line_edit = QLineEdit()
    line_edit.setPlaceholderText(placeholder_text)

    browse_button = QPushButton("Browse")
    browse_button.clicked.connect(browse_callback)
    browse_button.setFixedWidth(90)

    row_layout = QHBoxLayout()
    row_layout.addWidget(line_edit)
    row_layout.addWidget(browse_button)

    layout = QVBoxLayout()
    layout.addWidget(label)
    layout.addLayout(row_layout)

    return line_edit, layout


def configure_status_label(label, text, color):
    """Update a status label text and apply its color style."""
    label.setText(text)
    label.setStyleSheet(
        f"background-color: #1F2630; border: 1px solid #4A5568; "
        f"border-radius: 7px; padding: 8px; color: {color};"
    )
    QApplication.processEvents()


def find_stm32_programmer_cli():
    """Search common installation paths for STM32_Programmer_CLI.exe."""
    possible_paths = [
        r"C:\Program Files\STMicroelectronics\STM32Cube\STM32CubeProgrammer\bin\STM32_Programmer_CLI.exe",
        r"C:\Program Files (x86)\STMicroelectronics\STM32Cube\STM32CubeProgrammer\bin\STM32_Programmer_CLI.exe",
    ]

    for path in possible_paths:
        if os.path.isfile(path):
            return path

    return ""


def run_gui():
    """Create and run the main application GUI."""
    logging_thread = None
    logging_worker = None

    flash_thread = None
    flash_worker = None

    settings = QSettings("Eman", "STM32 Bring-up Tool")
    app = QApplication.instance() or QApplication(sys.argv)

    window = QWidget()
    window.setWindowTitle("STM32 Bring-up Tool")
    window.resize(500, 400)
    window.show()

    flash_frame, flash_layout = create_section_frame("Firmware Flashing")
    log_frame, log_layout = create_section_frame("Serial Logging")

    def browse_firmware_file():
        """Browse and select a firmware file."""
        file_path, _ = QFileDialog.getOpenFileName(
            window,
            "Select Firmware File",
            "",
            "HEX Files (*.hex);;Binary Files (*.bin);;All Files (*)"
        )
        if file_path:
            firmware_input.setText(file_path)

    def browse_cli_file():
        """Browse and select the STM32CubeProgrammer CLI executable."""
        file_path, _ = QFileDialog.getOpenFileName(
            window,
            "Select STM32CubeProgrammer CLI",
            "",
            "Executable Files (*.exe);;All Files (*)"
        )
        if file_path:
            cli_path_input.setText(file_path)

    port_input, port_layout = make_label_and_layout("Serial Port:", "e.g. COM4")
    baudrate_input, baudrate_layout = make_label_and_layout("Baud Rate:", "e.g. 115200")

    firmware_input, firmware_layout = make_label_and_browse_layout(
        "Firmware File Path:",
        r"e.g. firmware\stm32_bringup_automation_target.hex",
        browse_firmware_file
    )

    cli_path_input, cli_path_layout = make_label_and_browse_layout(
        "STM32CubeProgrammer CLI Path:",
        r"e.g. C:\Program Files\STMicroelectronics\STM32Cube\STM32CubeProgrammer\bin\STM32_Programmer_CLI.exe",
        browse_cli_file
    )

    # Restore saved user settings.
    port_input.setText(settings.value("port", ""))
    baudrate_input.setText(settings.value("baudrate", ""))
    firmware_input.setText(settings.value("firmware_path", ""))
    cli_path_input.setText(settings.value("cli_path", ""))

    flash_status_label = QLabel("")
    flash_status_label.setWordWrap(True)
    flash_status_label.setObjectName("resultLabel")

    log_status_label = QLabel("")
    log_status_label.setWordWrap(True)
    log_status_label.setObjectName("resultLabel")

    def handle_received_data(data):
        """Display the latest received serial data."""
        log_status_label.setText(f"Last data: {data}")

    def handle_status_message(message):
        """Display normal logging status messages."""
        configure_status_label(log_status_label, message, "lightgreen")

    def stop_logging():
        """Request the logging worker to stop."""
        start_log_button.setEnabled(True)
        stop_log_button.setEnabled(False)

        nonlocal logging_worker
        if logging_worker is not None:
            logging_worker.stop()
            log_status_label.setText("Stopping logging...")

    def handle_logging_error(message):
        """Display logging errors."""
        start_log_button.setEnabled(True)
        configure_status_label(log_status_label, f"Logging error: {message} ", "red")

    def cleanup_logging_objects():
        """Clear logging thread and worker references after completion."""
        nonlocal logging_thread, logging_worker
        logging_thread = None
        logging_worker = None

    def start_logging():
        """Validate inputs and start serial logging in a worker thread."""
        nonlocal logging_thread, logging_worker

        baudrate = baudrate_input.text().strip()
        port = port_input.text().strip()

        if baudrate == "":
            QMessageBox.warning(window, "Invalid Input", "Baudrate is empty")
            return

        if not baudrate.isdigit():
            QMessageBox.warning(window, "Invalid Input", "Baudrate must be a number.")
            return

        if port == "":
            QMessageBox.warning(window, "Invalid Input", "Port is empty")
            return

        if logging_worker is not None:
            QMessageBox.information(window, "Logging", "Logging is already running.")
            return

        start_log_button.setEnabled(False)
        stop_log_button.setEnabled(True)

        # Save the latest logging settings.
        settings.setValue("port", port)
        settings.setValue("baudrate", baudrate)

        log_file_name = create_log_filename()
        logging_thread = QThread()
        logging_worker = SerialLoggerWorker(port, int(baudrate), log_file_name)

        logging_worker.moveToThread(logging_thread)

        logging_thread.started.connect(logging_worker.run)
        logging_worker.data_received.connect(handle_received_data)
        logging_worker.status_message.connect(handle_status_message)
        logging_worker.error_occurred.connect(handle_logging_error)

        # Clean up thread and worker when logging finishes.
        logging_worker.finished.connect(logging_thread.quit)
        logging_worker.finished.connect(logging_worker.deleteLater)
        logging_thread.finished.connect(cleanup_logging_objects)
        logging_thread.finished.connect(logging_thread.deleteLater)

        logging_thread.start()

    def cleanup_flash_objects():
        """Clear flash thread and worker references after completion."""
        nonlocal flash_thread, flash_worker
        flash_thread = None
        flash_worker = None

    def handle_flash_result(success, message):
        """Display the result of the flashing process."""
        flash_button.setEnabled(True)

        if not success:
            configure_status_label(flash_status_label, f"Flashing failed:\n{message}", "red")
        else:
            configure_status_label(flash_status_label, "Firmware flashed successfully!", "lightgreen")

    def flash_firmware():
        """Validate inputs and start firmware flashing in a worker thread."""
        nonlocal flash_thread, flash_worker

        firmware_path = firmware_input.text().strip()
        cli_path = cli_path_input.text().strip()

        # Try to auto-detect the CLI path if the field is empty.
        if not cli_path:
            cli_path = find_stm32_programmer_cli()

        if cli_path:
            cli_path_input.setText(cli_path)

        if not os.path.isfile(firmware_path):
            flash_status_label.setText("")
            QApplication.processEvents()
            QMessageBox.warning(window, "Invalid input", "firmware path does not exist")
            return

        if not os.path.isfile(cli_path):
            configure_status_label(flash_status_label, "", "white")
            QMessageBox.warning(window, "Invalid input", "STM32CubeProgrammer CLI path does not exist")
            return

        settings.setValue("firmware_path", firmware_path)
        settings.setValue("cli_path", cli_path)

        configure_status_label(flash_status_label, "uploading firmware...", "lightyellow")
        flash_button.setEnabled(False)

        flash_thread = QThread()
        flash_worker = FlashWorker(firmware_path, cli_path)

        flash_worker.moveToThread(flash_thread)

        flash_thread.started.connect(flash_worker.run)
        flash_worker.finished.connect(handle_flash_result)
        flash_worker.finished.connect(flash_thread.quit)
        flash_worker.finished.connect(flash_worker.deleteLater)
        flash_thread.finished.connect(flash_thread.deleteLater)
        flash_thread.finished.connect(cleanup_flash_objects)

        flash_thread.start()

    app.setStyleSheet("""
    QWidget {
        background-color: #1E1E1E;
        color: #EAEAEA;
        font-size: 10pt;
    }

    QFrame#sectionFrame {
        background-color: #2C3440;
        border: 1px solid #4A5568;
        border-radius: 12px;
    }

    QLabel#sectionTitle {
        background-color: #5DADE2;
        color: #1E2A38;
        font-size: 11pt;
        font-weight: bold;
        padding: 5px 12px;
        border-radius: 9px;
    }

    QLabel#headerLabel {
        font-size: 15pt;
        font-weight: 600;
        color: white;
        padding: 4px;
    }

    QLineEdit {
        background-color: #F0F0F0;
        color: #202020;
        border-radius: 7px;
        padding: 6px;
        border: 1px solid #999999;
    }

    QPushButton {
        background-color: #355C8C;
        color: white;
        border-radius: 10px;
        padding: 8px;
        font-weight: bold;
    }

    QPushButton:hover {
        background-color: #4A74A8;
    }

    QPushButton:pressed {
        background-color: #2A4A70;
    }

    QLabel {
        background-color: transparent;
        color: #EAEAEA;
    }

    QLabel#resultLabel {
        background-color: #1F2630;
        border: 1px solid #4A5568;
        border-radius: 7px;
        padding: 8px;
        color: #EAEAEA;
    }
    """)

    flash_button = QPushButton("Flash Firmware")
    start_log_button = QPushButton("Start Logging")
    stop_log_button = QPushButton("Stop Logging")
    open_log_file_button = QPushButton("Open Log Folder")

    flash_button.clicked.connect(flash_firmware)
    start_log_button.clicked.connect(start_logging)
    stop_log_button.clicked.connect(stop_logging)
    open_log_file_button.clicked.connect(open_log_file)

    flash_layout.addLayout(firmware_layout)
    flash_layout.addLayout(cli_path_layout)
    flash_layout.addWidget(flash_button)
    flash_layout.addWidget(flash_status_label)

    log_layout.addLayout(port_layout)
    log_layout.addLayout(baudrate_layout)
    log_layout.addWidget(start_log_button)
    log_layout.addWidget(stop_log_button)
    log_layout.addWidget(open_log_file_button)
    log_layout.addWidget(log_status_label)

    main_layout = QVBoxLayout()
    main_layout.setContentsMargins(12, 12, 12, 12)
    main_layout.setSpacing(12)

    header_label = QLabel("STM32 Bring-up Tool")
    header_label.setAlignment(Qt.AlignCenter)
    header_label.setObjectName("headerLabel")

    footer_label = QLabel("Version 1.0  |  Developed by Eman")
    footer_label.setAlignment(Qt.AlignCenter)
    footer_label.setStyleSheet("color: gray; font-size: 10pt;")

    main_layout.addWidget(header_label)
    main_layout.addWidget(flash_frame)
    main_layout.addWidget(log_frame)
    main_layout.addWidget(footer_label)

    window.setLayout(main_layout)

    def on_about_to_quit():
        """Stop running threads safely before the application exits."""
        nonlocal logging_thread, logging_worker, flash_thread, flash_worker

        if logging_worker is not None:
            logging_worker.stop()

            if logging_thread is not None and logging_thread.isRunning():
                logging_thread.quit()
                logging_thread.wait()

        if flash_thread is not None and flash_thread.isRunning():
            flash_thread.quit()
            flash_thread.wait()

    app.aboutToQuit.connect(on_about_to_quit)

    sys.exit(app.exec())

    return "GUI Closed"