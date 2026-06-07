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

import sys
import subprocess
import os
import re
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox
from PySide6.QtUiTools import QUiLoader
from PySide6.QtCore import QFile, QThread, Signal

def get_bundle_dir():
    if hasattr(sys, "frozen"):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


class DownloadWorker(QThread):
    """Wątek tła, który pobiera dane z yt-dlp i na bieżąco aktualizuje pasek postępu"""
    progress_changed = Signal(int)  # Wysyła procenty (0-100) do głównego okna
    finished = Signal(bool, str)    # Wysyła wynik (sukces, tekst_wyjsciowy) po zakończeniu

    def __init__(self, command):
        super().__init__()
        self.command = command

    def run(self):
        try:
            # Odpalamy proces i łączymy stdout ze stderr
            process = subprocess.Popen(
                self.command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                errors='ignore',
                bufsize=1
            )

            full_output = []
            
            # Czytamy linie z yt-dlp w czasie rzeczywistym
            while True:
                line = process.stdout.readline()
                if not line and process.poll() is not None:
                    break
                
                if line:
                    full_output.append(line)
                    # Szukamy procentów w tekście yt-dlp (np. "[download]  45.2% of...")
                    match = re.search(r'(\d+\.\d+)%', line)
                    if match:
                        percentage = int(float(match.group(1)))
                        self.progress_changed.emit(percentage)

            process.wait()
            output_text = "".join(full_output)

            if process.returncode == 0:
                self.finished.emit(True, "OK")
            else:
                self.finished.emit(False, output_text)

        except Exception as e:
            self.finished.emit(False, str(e))


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
        
        # Ukrywamy pasek postępu na starcie aplikacji
        self.ui.progressBar.setHidden(True)
        self.ui.progressBar.setValue(0)
        
        # Podpięcie przycisku do akcji
        self.ui.pushButton.clicked.connect(self.save_file_dialog)

    def save_file_dialog(self):
        # Pobieramy URL i czyścimy z przypadkowych spacji (idiotoodporność)
        url = self.ui.uRLFilmuLineEdit.text().strip()
        if not url:
            QMessageBox.warning(self.ui, "Błąd", "Wklej najpierw URL do filmu!")
            return

        current_index = self.ui.formatComboBox.currentIndex()
        bundle_dir = get_bundle_dir()
        ytdlp_exe = os.path.join(bundle_dir, "yt-dlp.exe")

        # Sprawdzamy, czy w ogóle mamy plik yt-dlp.exe obok programu
        if not os.path.exists(ytdlp_exe):
            QMessageBox.critical(self.ui, "Błąd krytyczny", "Brak pliku silnika pobierania (yt-dlp.exe)!")
            return

        match current_index:
            case 0:  # Opcja: FILM
                file_path, _ = QFileDialog.getSaveFileName(
                    self.ui, "Zapisz film jako...", "", "Pliki wideo (*.mp4)"
                )
                if not file_path: 
                    return
                if not file_path.endswith('.mp4'): 
                    file_path += '.mp4'
                
                # Przygotowanie szablonu nazwy dla yt-dlp bez dublowania .mp4
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
                self.start_download_thread(command)

            case 1:  # Opcja: DŹWIĘK (MP3)
                file_path, _ = QFileDialog.getSaveFileName(
                    self.ui, "Zapisz dźwięk jako...", "", "Pliki audio (*.mp3)"
                )
                if not file_path: 
                    return
                if not file_path.endswith('.mp3'): 
                    file_path += '.mp3'
                
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
                self.start_download_thread(command)

    def start_download_thread(self, command):
        # Blokujemy przycisk, zerujemy i pokazujemy pasek postępu
        self.ui.pushButton.setEnabled(False)
        self.ui.progressBar.setValue(0)
        self.ui.progressBar.setHidden(False)

        # Odpalenie wątku roboczego
        self.worker = DownloadWorker(command)
        self.worker.progress_changed.connect(self.ui.progressBar.setValue)
        self.worker.finished.connect(self.on_download_finished)
        self.worker.start()

    def on_download_finished(self, success, output_text):
        # Przywracamy wygląd interfejsu
        self.ui.progressBar.setHidden(True)
        self.ui.pushButton.setEnabled(True)

        if success:
            QMessageBox.information(self.ui, "Sukces", "Pobieranie zakończone pomyślnie!")
        else:
            error_msg = "Wystąpił nieznany problem z zapisem pliku."
            if "ERROR:" in output_text:
                for line in output_text.splitlines():
                    if line.startswith("ERROR:"):
                        error_msg = f"YouTube zgłosił problem:\n{line.replace('ERROR:', '').strip()}"
                        break
            QMessageBox.critical(self.ui, "Błąd pobierania", error_msg)

    def show(self):
        self.ui.show()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = DownloaderApp()
    window.show()
    sys.exit(app.exec())