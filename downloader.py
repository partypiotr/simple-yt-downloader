#nuitka-project:--onefile
#nuitka-project:--onefile-tempdir-spec={CACHE_DIR}/{PRODUCT}/{VERSION}
#nuitka-project:--plugin-enable=pyside6
#nuitka-project:--include-data-files=design.ui=design.ui
#nuitka-project:--include-data-files=ffmpeg.exe=ffmpeg.exe
#nuitka-project:--include-data-files=ffprobe.exe=ffprobe.exe
#nuitka-project:--include-data-files=yt-dlp.exe=yt-dlp.exe
#nuitka-project:--company-name="Piotr Kiryk @ 3ForceIT"
#nuitka-project:--product-name="SnatchIt"
#nuitka-project:--product-version=2.0.0
#nuitka-project:--windows-console-mode=attach
#nuitka-project:--python-flag=no_site
#nuitka-project:--python-flag=no_docstrings

import sys
import subprocess
import os
import re
import glob
import json
import urllib.request
import urllib.error

# pylint: disable=import-error
# pyrefly: ignore [missing-import]
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox
# pyrefly: ignore [missing-import]
from PySide6.QtUiTools import QUiLoader
# pyrefly: ignore [missing-import]
from PySide6.QtCore import QFile, QThread, Signal
# pylint: enable=import-error

YTDLP_BIN = "yt-dlp.exe"
APP_VERSION = "2.0.0"
REPORT_URL = "https://partypiotr.xyz/snatchit/error-reporting.php"

# Ordered list of (substring_to_match, polish_message) pairs.
# First match wins — put more specific patterns before general ones.
_ERROR_TRANSLATIONS = [
    # Availability
    ("video unavailable",          "Film jest niedostępny (usunięty lub zablokowany)."),
    ("this video is private",       "Film jest prywatny — autor go ukrył."),
    ("private video",               "Film jest prywatny — autor go ukrył."),
    ("members only",                "Film jest dostępny tylko dla członków kanału."),
    ("join this channel",           "Film jest dostępny tylko dla członków kanału."),
    # Age / sign-in
    ("sign in to confirm your age", "YouTube wymaga weryfikacji wieku — nie można pobrać bez konta."),
    ("age-restricted",              "Film ma ograniczenie wiekowe — nie można go pobrać."),
    ("confirm your age",            "Film ma ograniczenie wiekowe — nie można go pobrać."),
    ("sign in",                     "YouTube wymaga zalogowania się, aby pobrać ten film."),
    # Geo-blocking
    ("not available in your country", "Film jest zablokowany w Twoim kraju."),
    ("geo",                         "Film jest zablokowany w Twoim kraju."),
    # Network
    ("unable to download webpage",  "Brak połączenia z internetem lub YouTube jest niedostępny."),
    ("network",                     "Wystąpił błąd sieciowy — sprawdź połączenie z internetem."),
    ("timed out",                   "Połączenie z YouTube przekroczyło limit czasu. Spróbuj ponownie."),
    ("connection reset",            "Połączenie zostało przerwane. Spróbuj ponownie."),
    ("connectionreset",             "Połączenie zostało przerwane. Spróbuj ponownie."),
    # Bad URL / not found
    ("is not a valid url",          "Podany adres URL jest nieprawidłowy."),
    ("unsupported url",             "Ten adres URL nie jest obsługiwany. SnatchIt działa tylko z YouTube."),
    ("no video formats found",      "YouTube nie udostępnił żadnego formatu wideo dla tego filmu."),
    ("requested format is not available", "Wybrany format nie jest dostępny dla tego filmu."),
    # ffmpeg
    ("ffmpeg",                      "Wystąpił błąd podczas przetwarzania dźwięku/wideo (ffmpeg)."),
    # Disk
    ("no space left",               "Brak miejsca na dysku — zwolnij trochę miejsca i spróbuj ponownie."),
    ("permission denied",           "Brak uprawnień do zapisu pliku w wybranym miejscu."),
    ("access is denied",            "Brak uprawnień do zapisu pliku w wybranym miejscu."),
    # Playlist / live
    ("is a playlist",               "Podany link prowadzi do playlisty — wklej link do pojedynczego filmu."),
    ("live event",                  "Ten film to transmisja na żywo — nie można jej pobrać."),
    ("this live event will begin",  "Transmisja jeszcze się nie rozpoczęła."),
]


def _translate_error(raw_output: str) -> tuple[str, bool]:
    """Returns (polish_message, is_known_error)."""
    lowered = raw_output.lower()
    for keyword, polish_msg in _ERROR_TRANSLATIONS:
        if keyword.lower() in lowered:
            return polish_msg, True
    return "Wystąpił nieoczekiwany błąd podczas pobierania.", False


def _send_error_report(raw_error: str) -> bool:
    payload = json.dumps({
        "app_version": APP_VERSION,
        "error_text": raw_error[:2000],
    }).encode("utf-8")
    req = urllib.request.Request(
        REPORT_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent": f"SnatchIT/{APP_VERSION}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except (urllib.error.URLError, urllib.error.HTTPError, OSError):
        return False


def get_bundle_dir() -> str:
    # Nuitka compiled binaries expose __compiled__ in module globals.
    # sys.frozen is PyInstaller-only and is never set by Nuitka.
    if globals().get("__compiled__") or getattr(sys, "frozen", False):
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
                stdin=subprocess.DEVNULL,
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
                stdin=subprocess.DEVNULL,
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

        # Debug trigger: type "debug:report" to test the error report dialog
        if url == "debug:report":
            self.on_download_finished(False, "ERROR: [debug] Simulated unknown error for testing")
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
            return
        if success:
            QMessageBox.information(self.ui, "Sukces", "Pobieranie zakończone pomyślnie!")
            return

        raw_error = output_text.strip()
        for line in output_text.splitlines():
            if line.startswith("ERROR:"):
                raw_error = line.replace("ERROR:", "").strip()
                break

        friendly, is_known = _translate_error(raw_error)

        if is_known:
            QMessageBox.critical(self.ui, "Błąd pobierania", friendly)
        else:
            msg_box = QMessageBox(self.ui)
            msg_box.setIcon(QMessageBox.Critical)
            msg_box.setWindowTitle("Błąd pobierania")
            msg_box.setText(friendly)
            msg_box.setInformativeText(
                "Możesz zgłosić ten błąd do 3ForceIT, abyśmy mogli go naprawić.\n"
                "Zgłoszenie wyśle jedynie informację o błędzie \u2014 "
                "nie zawiera żadnych danych osobowych."
            )
            close_btn = msg_box.addButton("Zamknij", QMessageBox.RejectRole)
            report_btn = msg_box.addButton("Zgłoś błąd", QMessageBox.AcceptRole)
            msg_box.setDefaultButton(close_btn)
            msg_box.exec()

            if msg_box.clickedButton() == report_btn:
                if _send_error_report(raw_error):
                    QMessageBox.information(
                        self.ui, "Dziękujemy",
                        "Zgłoszenie zostało wysłane. Dziękujemy za pomoc!"
                    )
                else:
                    QMessageBox.warning(
                        self.ui, "Problem z wysłaniem",
                        "Nie udało się wysłać zgłoszenia \u2014 "
                        "sprawdź połączenie z internetem."
                    )

    def show(self):
        self.ui.show()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = DownloaderApp()
    window.show()
    sys.exit(app.exec())