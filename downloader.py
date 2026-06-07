#nuitka-project:--onefile
#nuitka-project:--plugin-enable=pyside6
#nuitka-project:--include-data-files=design.ui=design.ui
#nuitka-project:--include-data-files=ffmpeg.exe=ffmpeg.exe
#nuitka-project:--include-data-files=ffprobe.exe=ffprobe.exe
#nuitka-project:--include-data-files=yt-dlp.exe=yt-dlp.exe
#nuitka-project:--company-name="Piotr Kiryk @ 3ForceIT"
#nuitka-project:--product-name="Pobieracz Youtube"
#nuitka-project:--product-version=1.3.0
#nuitka-project:--windows-console-mode=attach
"""Prosty pobieracz filmów i audio z YouTube oparty na yt-dlp i PySide6."""

import sys
import subprocess
import os
import re

# pylint: disable=import-error
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox
from PySide6.QtUiTools import QUiLoader
from PySide6.QtCore import QFile, QThread, Signal
# pylint: enable=import-error

YTDLP_BIN = "yt-dlp.exe"


def get_bundle_dir() -> str:
    """Zwraca katalog, w którym znajduje się plik wykonywalny lub skrypt."""
    if hasattr(sys, "frozen"):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


class DownloadWorker(QThread):
    """Wątek tła pobierający dane z yt-dlp i raportujący postęp do głównego okna."""

    progress_changed = Signal(int)  # Wysyła procenty (0-100) do głównego okna
    status_changed = Signal(str)    # Wysyła aktualny tekst statusu
    finished = Signal(bool, str)    # Wysyła wynik (sukces, tekst_wyjsciowy) po zakończeniu

    def __init__(self, command):
        """Inicjalizuje wątek z podaną komendą do uruchomienia."""
        super().__init__()
        self.command = command
        self._process = None

    def run(self):
        """Uruchamia proces yt-dlp i na bieżąco przekazuje postęp przez sygnały."""
        try:
            # Nie możemy użyć 'with' — potrzebujemy referencji do _process w cancel()
            self._process = subprocess.Popen(  # pylint: disable=consider-using-with
                self.command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                errors='ignore',
                bufsize=1
            )

            full_output = []

            while True:
                line = self._process.stdout.readline()
                if not line and self._process.poll() is not None:
                    break

                if line:
                    full_output.append(line)
                    match = re.search(r'(\d+\.\d+)%', line)
                    if match:
                        percentage = int(float(match.group(1)))
                        self.progress_changed.emit(percentage)
                    status = re.sub(r'\x1b\[[0-9;]*m', '', line).strip()
                    if status:
                        self.status_changed.emit(status)

            self._process.wait()
            output_text = "".join(full_output)

            if self._process.returncode == 0:
                self.finished.emit(True, "OK")
            else:
                self.finished.emit(False, output_text)

        except (OSError, subprocess.SubprocessError) as e:
            self.finished.emit(False, str(e))

    def cancel(self):
        """Kończy proces yt-dlp jeśli jest uruchomiony."""
        if self._process and self._process.poll() is None:
            self._process.terminate()


class DownloaderApp:
    """Główna klasa aplikacji — ładuje UI i obsługuje logikę pobierania."""

    def __init__(self):
        """Ładuje plik interfejsu i podpina sygnały do slotów."""
        loader = QUiLoader()
        ui_file_path = os.path.join(get_bundle_dir(), "design.ui")
        ui_file = QFile(ui_file_path)
        if not ui_file.open(QFile.ReadOnly):
            QMessageBox.critical(None, "Błąd", "Nie znaleziono pliku interfejsu (design.ui)!")
            sys.exit(1)

        self.ui = loader.load(ui_file)
        ui_file.close()

        self.ui.progressBar.setHidden(True)
        self.ui.progressBar.setValue(0)
        self.ui.statusLabel.setHidden(True)
        self.ui.cancelButton.setHidden(True)

        self.ui.pushButton.clicked.connect(self.save_file_dialog)
        self.ui.cancelButton.clicked.connect(self.cancel_download)
        self.worker = None

    def _get_save_path(self, title: str, ext: str, filter_str: str) -> str | None:
        """Otwiera okno dialogowe zapisu i zwraca zweryfikowaną ścieżkę, lub None jeśli anulowano."""
        file_path, _ = QFileDialog.getSaveFileName(self.ui, title, "", filter_str)
        if not file_path:
            return None
        if not file_path.endswith(f'.{ext}'):
            file_path += f'.{ext}'
        return file_path

    def save_file_dialog(self):
        """Waliduje URL, otwiera okno zapisu i uruchamia pobieranie."""
        url = self.ui.uRLFilmuLineEdit.text().strip()
        if not url:
            QMessageBox.warning(self.ui, "Błąd", "Wklej najpierw URL do filmu!")
            return

        if not url.startswith(("http://", "https://")):
            QMessageBox.warning(self.ui, "Błąd", "Podany tekst nie wygląda jak poprawny adres URL.")
            return

        bundle_dir = get_bundle_dir()
        ytdlp_exe = os.path.join(bundle_dir, YTDLP_BIN)

        if not os.path.exists(ytdlp_exe):
            QMessageBox.critical(
                self.ui, "Błąd krytyczny",
                f"Brak pliku silnika pobierania ({YTDLP_BIN})!"
            )
            return

        current_index = self.ui.formatComboBox.currentIndex()

        match current_index:
            case 0:  # Opcja: FILM
                file_path = self._get_save_path("Zapisz film jako...", "mp4", "Pliki wideo (*.mp4)")
                if not file_path:
                    return
                out_template = file_path.rsplit('.', 1)[0] + ".%(ext)s"
                command = [
                    ytdlp_exe,
                    "--ffmpeg-location", bundle_dir,
                    "--no-part",
                    "--progress",
                    "--format", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
                    "--merge-output-format", "mp4",
                    "-o", out_template,
                    url
                ]

            case 1:  # Opcja: DŹWIĘK (MP3)
                file_path = self._get_save_path("Zapisz dźwięk jako...", "mp3", "Pliki audio (*.mp3)")
                if not file_path:
                    return
                out_template = file_path.rsplit('.', 1)[0] + ".%(ext)s"
                command = [
                    ytdlp_exe,
                    "--ffmpeg-location", bundle_dir,
                    "--no-part",
                    "--progress",
                    "--extract-audio",
                    "--audio-format", "mp3",
                    "-o", out_template,
                    url
                ]

            case _:
                return

        self.start_download_thread(command)

    def cancel_download(self):
        """Anuluje trwające pobieranie."""
        if self.worker and self.worker.isRunning():
            self.worker.cancel()

    def start_download_thread(self, command):
        """Blokuje UI, pokazuje pasek postępu i uruchamia wątek pobierania."""
        if self.worker and self.worker.isRunning():
            return

        self.ui.pushButton.setEnabled(False)
        self.ui.progressBar.setValue(0)
        self.ui.progressBar.setHidden(False)
        self.ui.statusLabel.setText("Łączenie...")
        self.ui.statusLabel.setHidden(False)
        self.ui.cancelButton.setHidden(False)

        self.worker = DownloadWorker(command)  # pylint: disable=attribute-defined-outside-init
        self.worker.progress_changed.connect(self.ui.progressBar.setValue)
        self.worker.status_changed.connect(self.ui.statusLabel.setText)
        self.worker.finished.connect(self.on_download_finished)
        self.worker.start()

    def on_download_finished(self, success, output_text):
        """Przywraca UI po zakończeniu pobierania i informuje o wyniku."""
        self.ui.progressBar.setValue(0)
        self.ui.progressBar.setHidden(True)
        self.ui.statusLabel.setHidden(True)
        self.ui.cancelButton.setHidden(True)
        self.ui.pushButton.setEnabled(True)

        if success:
            QMessageBox.information(self.ui, "Sukces", "Pobieranie zakończone pomyślnie!")
        else:
            error_msg = "Wystąpił nieznany problem z zapisem pliku."
            if "ERROR:" in output_text:
                for line in output_text.splitlines():
                    if line.startswith("ERROR:"):
                        error_msg = (
                            f"YouTube zgłosił problem:\n{line.replace('ERROR:', '').strip()}"
                        )
                        break
            QMessageBox.critical(self.ui, "Błąd pobierania", error_msg)

    def show(self):
        """Wyświetla główne okno aplikacji."""
        self.ui.show()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = DownloaderApp()
    window.show()
    sys.exit(app.exec())