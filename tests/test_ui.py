"""Widget behavior checks run in isolated QApplication processes."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import textwrap
import unittest


class WidgetTests(unittest.TestCase):
    def run_ui_check(self, code: str) -> None:
        prefix = """
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QWidget
from quiz_helper.models import AppSettings
from quiz_helper.ui import CropCanvas, FloatingPanel, SettingsPage, WindowPicker
app = QApplication([])
"""
        result = subprocess.run(
            [sys.executable, "-c", prefix + textwrap.dedent(code)],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_crop_canvas_maps_letterboxed_display_to_source_pixels(self) -> None:
        self.run_ui_check("""
            image = QImage(1000, 500, QImage.Format.Format_RGB32)
            canvas = CropCanvas(image)
            canvas.resize(500, 500)
            canvas.show()
            app.processEvents()
            assert canvas.image_rect() == QRect(0, 125, 500, 250)
            canvas.selection = QRect(50, 150, 200, 100)
            assert canvas.pixel_rect() == QRect(100, 50, 400, 200)
            canvas.selection = QRect(-100, -100, 800, 800)
            assert canvas.pixel_rect() == image.rect()
            canvas.resize(600, 500)
            app.processEvents()
            assert canvas.selection.isEmpty()
            canvas.close()
        """)

    def test_settings_roundtrip_and_conditional_controls(self) -> None:
        self.run_ui_check("""
            settings = AppSettings()
            page = SettingsPage(settings)
            assert page.read_settings() == settings
            assert not page.controls['jpeg_quality'].isEnabled()
            assert not page.controls['proxy_url'].isEnabled()
            page.controls['image_format'].setCurrentIndex(1)
            page.controls['proxy_mode'].setCurrentIndex(2)
            page.controls['proxy_url'].setText('http://127.0.0.1:7890')
            page.controls['auto_cleanup'].setChecked(False)
            page.controls['explanation'].setChecked(True)
            assert page.controls['jpeg_quality'].isEnabled()
            assert page.controls['proxy_url'].isEnabled()
            assert not page.controls['retention_minutes'].isEnabled()
            changed = page.read_settings()
            assert changed.image_format == 'JPEG'
            assert changed.proxy_mode == 'custom' and changed.explanation
            page.load(changed)
            assert page.read_settings() == changed
        """)

    def test_floating_panel_clears_answer_and_keeps_nonfocus_flag(self) -> None:
        self.run_ui_check("""
            panel = FloatingPanel()
            panel.apply_settings(AppSettings())
            panel.show_answer('A、C', '简短解析')
            assert panel.answer_text == 'A、C'
            assert panel.copy.isEnabled()
            assert not panel.expand.isHidden()
            assert panel.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus
            panel.clear_answer()
            assert panel.answer_text == '' and panel.answer.text() == '—'
            assert not panel.copy.isEnabled() and panel.expand.isHidden()
            panel.close()
        """)

    def test_window_picker_preserves_identity_for_duplicate_titles(self) -> None:
        self.run_ui_check("""
            from types import SimpleNamespace
            windows = [SimpleNamespace(title='同名窗口', window_id=111),
                       SimpleNamespace(title='同名窗口', window_id=222)]
            parent = QWidget()
            dialog = WindowPicker(windows, parent)
            dialog.list.setCurrentRow(1)
            assert dialog.selected().window_id == 222
            dialog.search.setText('0xde')
            assert dialog.list.item(0).isHidden()
            assert not dialog.list.item(1).isHidden()
            dialog.close()
            parent.close()
        """)

    def test_cancel_crop_after_minimize_keeps_paused_status(self) -> None:
        self.run_ui_check("""
            from pathlib import Path
            import tempfile
            from unittest.mock import patch
            from PySide6.QtWidgets import QDialog
            from quiz_helper.app import MainWindow
            from quiz_helper.storage import AppStorage
            with tempfile.TemporaryDirectory(prefix='ui-paused-', dir=Path.cwd()) as directory:
                window = MainWindow(AppStorage(Path(directory)))
                window.controller.running = True
                image = QImage(200, 160, QImage.Format.Format_RGB32)
                def reject_after_minimize(dialog):
                    window.controller.paused = True
                    return QDialog.DialogCode.Rejected
                with patch('quiz_helper.app.CropDialog.exec', reject_after_minimize), \\
                     patch.object(window.overlay, 'show'):
                    window._choose_region(image)
                assert '已暂停' in window.home.status_label.text()
                assert not window.home.query_button.isEnabled()
                window.close()
                app.processEvents()
        """)


if __name__ == "__main__":
    unittest.main()
