import datetime
import os
import subprocess
import time

import serial
from PySide6.QtCore import QObject, Signal, Slot


def flash_stm32_firmware(firmware_path, STM32_Programmer_CLI_path):
    """Flash STM32 firmware using STM32CubeProgrammer CLI."""
    programmer_cli = STM32_Programmer_CLI_path

    command = [
        programmer_cli,
        "-c", "port=SWD", "freq=4000",
        "-e", "all", "-w",
        firmware_path,
        "-v",
        "-rst"
    ]

    try:
        result = subprocess.run(
            command,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        return True, result.stdout

    except subprocess.CalledProcessError as e:
        error_text = e.stderr if e.stderr else e.stdout
        return False, error_text


class FlashWorker(QObject):
    """Worker object to run firmware flashing in a background thread."""
    finished = Signal(bool, str)

    def __init__(self, firmware_path, cli_path):
        super().__init__()
        self.firmware_path = firmware_path
        self.cli_path = cli_path

    @Slot()
    def run(self):
        """Execute firmware flashing and emit the result."""
        success, message = flash_stm32_firmware(self.firmware_path, self.cli_path)

        if success:
            # Small delay to allow the target board to reboot after flashing.
            time.sleep(2)

        self.finished.emit(success, message)


def create_log_filename():
    """Create a timestamped log file path inside the logs folder."""
    now = datetime.datetime.now()
    file_timestamp_str = now.strftime("%y-%m-%d_%H-%M-%S")
    os.makedirs("logs", exist_ok=True)
    log_filename = f"logs/test-log_{file_timestamp_str}.txt"
    return log_filename


def create_timestamp():
    """Create a timestamp string for log entries."""
    now = datetime.datetime.now()
    timestamp_str = now.strftime("%y-%m-%d   %H:%M:%S")
    return timestamp_str


class SerialLoggerWorker(QObject):
    """Worker object to read serial data and save it to a log file."""
    data_received = Signal(str)
    status_message = Signal(str)
    error_occurred = Signal(str)
    finished = Signal()

    def __init__(self, port, baudrate, log_file_name):
        super().__init__()
        self.port = port
        self.baudrate = baudrate
        self.log_file_name = log_file_name
        self._running = True
        self.ser = None
        self.error_happen = False

    @Slot()
    def run(self):
        """Open the serial port, read incoming data, and log it."""
        try:
            self.ser = serial.Serial(self.port, self.baudrate, timeout=0.1)
            self.status_message.emit(
                f"Connected to {self.port} at {self.baudrate} baud."
            )

            while self._running:
                if self.ser.in_waiting > 0:
                    data = self.ser.readline().decode("utf-8", errors="ignore").rstrip()

                    if data:
                        timestamp_str = create_timestamp()

                        with open(self.log_file_name, "a", encoding="utf-8") as log_file:
                            log_file.write(f"[{timestamp_str}] {data}\n")

                        self.data_received.emit(data)

                # Small delay to reduce CPU usage in the loop.
                time.sleep(0.01)

        except serial.SerialException:
            self.error_happen = True
            self.error_occurred.emit("Couldn't open serial port.")

        except Exception as e:
            self.error_happen = True
            self.error_occurred.emit(str(e))

        finally:
            # Close the serial port safely when logging stops.
            if self.ser is not None and self.ser.is_open:
                self.ser.close()

            if not self.error_happen:
                self.status_message.emit("Logging stopped.")

            self.finished.emit()

    def stop(self):
        """Stop the logging loop."""
        self._running = False