#nuitka-project:--onefile
#nuitka-project:--onefile-tempdir-spec={CACHE_DIR}/{PRODUCT}/{VERSION}
#nuitka-project:--plugin-enable=pyside6
#nuitka-project:--include-data-files=design.ui=design.ui
#nuitka-project:--include-data-files=ffmpeg.exe=ffmpeg.exe
#nuitka-project:--include-data-files=ffprobe.exe=ffprobe.exe
#nuitka-project:--include-data-files=yt-dlp.exe=yt-dlp.exe
#nuitka-project:--company-name="Piotr Kiryk @ 3ForceIT"
#nuitka-project:--product-name="Pobieracz Youtube"
#nuitka-project:--product-version=1.3.0
#nuitka-project:--windows-console-mode=attach
#nuitka-project:--python-flag=no_site
#nuitka-project:--python-flag=no_docstrings

import sys
import subprocess
import os
import re
import glob

# pylint: disable=import-error
# pyrefly: ignore [missing-import]
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox
# pyrefly: ignore [missing-import]
from PySide6.QtUiTools import QUiLoader
# pyrefly: ignore [missing-import]
from PySide6.QtCore import QFile, QThread, Signal
# pylint: enable=import-error

YTDLP_BIN = "yt-dlp.exe"


def get_bundle_dir() -> str:
    if hasattr(sys, "frozen"):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


class DownloadWorker(QThread):

    progress_changed = Signal(int)  
    status_changed = Signal(str)    
    finished = Signal(bool, str)    
    def __init__(self, command, output_base: str):
        super().__init__()
        self.command = command
        self._output_base = output_base
        self._process = None
        self._cancelled = False

    def run(self):
        try:
            self._process = subprocess.Popen( 
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

            if self._cancelled:
                self._cleanup_partial_files()
                self.finished.emit(True, "CANCELLED")
            elif self._process.returncode == 0:
                self.finished.emit(True, "OK")
            else:
                self.finished.emit(False, output_text)

        except (OSError, subprocess.SubprocessError) as e:
            self.finished.emit(False, str(e))

    def cancel(self):
        if self._process and self._process.poll() is None:
            self._cancelled = True
            subprocess.call(
                ['taskkill', '/F', '/T', '/PID', str(self._process.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )

    def _cleanup_partial_files(self):
        for f in glob.glob(self._output_base + '.*'):
            try:
                os.remove(f)
            except OSError:
                pass


class DownloaderApp:

    def __init__(self):
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
        file_path, _ = QFileDialog.getSaveFileName(self.ui, title, "", filter_str)
        if not file_path:
            return None
        if not file_path.endswith(f'.{ext}'):
            file_path += f'.{ext}'
        return file_path

    def save_file_dialog(self):
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

        output_base = None
        match current_index:
            case 0:  # Opcja: FILM
                file_path = self._get_save_path("Zapisz film jako...", "mp4", "Pliki wideo (*.mp4)")
                if not file_path:
                    return
                output_base = file_path.rsplit('.', 1)[0]
                out_template = output_base + ".%(ext)s"
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
                output_base = file_path.rsplit('.', 1)[0]
                out_template = output_base + ".%(ext)s"
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

        self.start_download_thread(command, output_base)

    def cancel_download(self):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()

    def start_download_thread(self, command, output_base: str):
        if self.worker and self.worker.isRunning():
            return

        self.ui.pushButton.setEnabled(False)
        self.ui.progressBar.setValue(0)
        self.ui.progressBar.setHidden(False)
        self.ui.statusLabel.setText("Łączenie...")
        self.ui.statusLabel.setHidden(False)
        self.ui.cancelButton.setHidden(False)

        self.worker = DownloadWorker(command, output_base)  
        self.worker.progress_changed.connect(self.ui.progressBar.setValue)
        self.worker.status_changed.connect(self.ui.statusLabel.setText)
        self.worker.finished.connect(self.on_download_finished)
        self.worker.start()

    def on_download_finished(self, success, output_text):
        self.ui.progressBar.setValue(0)
        self.ui.progressBar.setHidden(True)
        self.ui.statusLabel.setHidden(True)
        self.ui.cancelButton.setHidden(True)
        self.ui.pushButton.setEnabled(True)

        if success and output_text == "CANCELLED":
            return  # user cancelled — silently restore UI, no dialog
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
        self.ui.show()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = DownloaderApp()
    window.show()
    sys.exit(app.exec())