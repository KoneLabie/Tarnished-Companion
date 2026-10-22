"""Render the shared browser overlay into a Windows per-pixel-alpha window.

WinForms/WebView2 cannot composite CSS alpha directly onto the desktop. The
offscreen WebView renders the same /overlay page used by OBS, then the small
native presenter displays its transparent PNG through UpdateLayeredWindow.
"""
import ctypes
import json
import logging
import math
import os
import subprocess
from datetime import datetime
from pathlib import Path
import threading
from urllib.request import urlopen


def interactive_regions(regions, viewport_width, viewport_height):
    """Validate page hit boxes and clip them to the CSS viewport."""
    if (type(viewport_width) not in (int, float) or type(viewport_height) not in (int, float)
            or not 1 <= viewport_width <= 10000 or not 1 <= viewport_height <= 10000
            or not math.isfinite(viewport_width) or not math.isfinite(viewport_height)
            or not isinstance(regions, list) or len(regions) > 64):
        raise ValueError('Invalid overlay control viewport.')
    rectangles = []
    for region in regions:
        if not isinstance(region, dict):
            raise ValueError('Invalid overlay control rectangle.')
        values = [region.get(key) for key in ('x', 'y', 'width', 'height')]
        if any(type(value) not in (int, float) or not -10000 <= value <= 10000
               or not math.isfinite(value) for value in values):
            raise ValueError('Invalid overlay control coordinates.')
        x, y, w, h = values
        if w < 0 or h < 0:
            raise ValueError('Invalid overlay control dimensions.')
        left, top = max(0, x), max(0, y)
        right, bottom = min(viewport_width, x+w), min(viewport_height, y+h)
        if right > left and bottom > top:
            rectangles.extend((float(left), float(top), float(right-left), float(bottom-top)))
    return rectangles, float(viewport_width), float(viewport_height)


def stop_owned_overlay(process, grace_seconds=5, terminate_seconds=2):
    """Close the private owner pipe, then reap only this exact Popen child."""
    if process is None:
        return True
    if process.stdin is not None:
        try:
            process.stdin.close()
        except OSError:
            pass
    try:
        if process.poll() is not None:
            return True
        try:
            process.wait(timeout=grace_seconds)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=terminate_seconds)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=terminate_seconds)
        return True
    except (OSError, subprocess.TimeoutExpired):
        logging.exception('The owned personal overlay did not finish shutdown.')
        return process.poll() is not None


def _read_owner_pipe():
    if os.name != 'nt':
        return os.read(0, 1)
    # Windowed PyInstaller sets sys.stdin to None, but Popen's pipe is still
    # available as the Windows standard-input handle.
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetStdHandle.argtypes = [wintypes.DWORD]
    kernel.GetStdHandle.restype = wintypes.HANDLE
    kernel.ReadFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                               ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    kernel.ReadFile.restype = wintypes.BOOL
    buffer, count = ctypes.create_string_buffer(1), wintypes.DWORD()
    if not kernel.ReadFile(kernel.GetStdHandle(-10), buffer, 1, ctypes.byref(count), None):
        return b''
    return buffer.raw[:count.value]


def watch_owner_pipe(disconnected, read=None):
    """EOF covers both a deliberate close and an unexpectedly ended owner."""
    try:
        while (read or _read_owner_pipe)():
            pass
    except OSError:
        pass
    disconnected()


def run(port, root, owned=False):
    owner_closed = threading.Event()
    if owned:
        threading.Thread(target=watch_owner_pipe, args=(owner_closed.set,), daemon=True).start()
    try:
        return _run(port, root, owner_closed if owned else None)
    except Exception:
        # An owner closing during startup is expected, not a WebView failure.
        if owned and owner_closed.wait(.1):
            return
        raise


def _run(port, root, owner_closed):
    if owner_closed is not None and owner_closed.is_set():
        return
    import webview
    try:ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('TarnishedLineup.Overlay')
    except (OSError,AttributeError):pass

    with urlopen(f'http://127.0.0.1:{port}/api/state', timeout=3) as response:
        state = json.load(response)
    width = max(280, min(600, int(state.get('layout', {}).get('width', 360))))
    log_dir = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'TarnishedLineup'
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger('tarnished.desktop')
    handler = logging.FileHandler(log_dir / 'overlay.log', encoding='utf-8')
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    # This renderer must stay shown to keep WebView2 captures running, but it
    # lives offscreen and is absent from the taskbar. Only the presenter is seen.
    renderer = webview.create_window(
        'Tarnished Lineup renderer', f'http://127.0.0.1:{port}/overlay',
        width=width, height=560, x=-10000, y=-10000,
        min_size=(200, 100), frameless=True, resizable=False,
        transparent=True, focus=False, easy_drag=False,
    )

    class Controller:
        def __init__(self):
            self.presenter = None
            self.timer = None
            self.busy = False
            self.closing = False
            self.debug_saved = False
            self.animation_active = False
            self.control_regions = ([], float(width), 560.0)
            self.export_lock = threading.Lock()
            # Optional diagnostics use the rendered PNG, including its alpha.
            # No files are emitted unless this explicit developer setting exists.
            debug_directory = os.environ.get('TARNISHED_OVERLAY_DEBUG_FRAMES')
            self.debug_frames_dir = Path(debug_directory) if debug_directory else None
            self.debug_frame_count = 0

        def set_interactive_regions(self, regions, viewport_width, viewport_height):
            if self.closing:
                return False
            try:
                validated = interactive_regions(regions, viewport_width, viewport_height)
            except (ValueError, OverflowError):
                return False
            self.control_regions = validated
            if self.presenter is not None:
                from System import Action
                renderer.native.BeginInvoke(Action(self.apply_regions))
            return True

        def apply_regions(self):
            if self.closing or self.presenter is None:
                return
            from System import Array, Double
            rectangles, viewport_width, viewport_height = self.control_regions
            self.presenter.SetInteractiveRegions(Array[Double](rectangles), viewport_width, viewport_height)

        def click(self, x, y):
            if self.closing:
                return
            # Already on the renderer's UI thread: use its asynchronous WebView
            # API directly, rather than block that thread with evaluate_js().
            coordinates = json.dumps([float(x), float(y)])
            renderer.native.webview.CoreWebView2.ExecuteScriptAsync(
                f'window.overlayNativeClick?.(...{coordinates})')

        def export_speedrun(self):
            """Only an explicit Export click can open the native save dialog."""
            if self.closing or self.presenter is None:
                return {'error': 'The overlay is closing. Open it again to export.'}
            if not self.export_lock.acquire(blocking=False):
                return {'error': 'An export dialog is already open.'}
            try:
                with urlopen(f'http://127.0.0.1:{port}/api/speedrun/export', timeout=5) as response:
                    raw = response.read(8 * 1024 * 1024 + 1)
                if len(raw) > 8 * 1024 * 1024:
                    raise ValueError('The speedrun export exceeds the supported size.')
                from System import Action, Environment
                from System.Windows.Forms import DialogResult, SaveFileDialog
                result = {'cancelled': True}

                def choose_path():
                    if self.closing:
                        return
                    dialog = SaveFileDialog()
                    try:
                        dialog.Title = 'Export speedrun statistics'
                        dialog.Filter = 'Tarnished encrypted runs (*.tlrun)|*.tlrun'
                        dialog.DefaultExt = 'tlrun'
                        dialog.AddExtension = True
                        dialog.OverwritePrompt = True
                        dialog.CheckPathExists = True
                        dialog.InitialDirectory = Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments)
                        dialog.FileName = 'Tarnished-Speedrun-' + datetime.now().strftime('%Y-%m-%d-%H%M%S') + '.tlrun'
                        if dialog.ShowDialog(self.presenter) == DialogResult.OK:
                            result.clear()
                            result['path'] = str(dialog.FileName)
                    finally:
                        dialog.Dispose()

                renderer.native.Invoke(Action(choose_path))
                if 'path' in result:
                    Path(result['path']).write_bytes(raw)
                return result
            except Exception as error:
                logger.exception('Could not export speedrun report')
                return {'error': 'Could not export the speedrun report: ' + str(error)}
            finally:
                self.export_lock.release()

        def set_animation_active(self, active):
            """The shared page requests smooth capture only while its glow moves."""
            if self.closing or not isinstance(active, bool):
                return
            self.animation_active = active
            if self.timer is not None:
                from System import Action
                def apply_cadence():
                    if not self.closing and self.timer is not None:
                        self.timer.Interval = 67 if self.animation_active else 500
                renderer.native.BeginInvoke(Action(apply_cadence))

        def resize(self, requested_width, requested_height):
            if self.closing:
                return
            try:
                w = max(280, min(600, int(requested_width)))
                h = max(100, min(1400, int(requested_height)))
            except (ValueError, TypeError, OverflowError):
                return
            renderer.resize(w, h)

        def close(self):
            if not self.closing:
                self.closing = True
                renderer.destroy()

        def before_show(self):
            # ShowInTaskbar recreates the WinForms handle and aborts WebView2
            # initialization. Adjust only the extended style on this handle.
            user32 = ctypes.windll.user32
            get_style = user32.GetWindowLongPtrW
            get_style.argtypes = [ctypes.c_void_p, ctypes.c_int]
            get_style.restype = ctypes.c_ssize_t
            set_style = user32.SetWindowLongPtrW
            set_style.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t]
            set_style.restype = ctypes.c_ssize_t
            hwnd = renderer.native.Handle.ToInt64()
            set_style(hwnd, -20, (get_style(hwnd, -20) | 0x80) & ~0x40000)

        def loaded(self):
            import clr
            from System import Action
            clr.AddReference(str(Path(root) / 'native' / 'LayeredOverlay.dll'))
            renderer.native.Invoke(Action(self.start_presenter))

        def start_presenter(self):
            from System import Action, String
            from System.Threading.Tasks import Task
            from System.Windows.Forms import Timer
            from TarnishedLineup.Native import LayeredOverlay

            if self.presenter is not None or self.closing:
                return
            screen_width = ctypes.windll.user32.GetSystemMetrics(0)
            self.presenter = LayeredOverlay(max(0, screen_width-width-24), 42)
            from System.Drawing import Icon
            icon_path=Path(root)/'assets'/'app-icon.ico'
            if icon_path.is_file():
                self.program_icon=Icon(str(icon_path));self.presenter.Icon=self.program_icon
            self.presenter.FormClosed += lambda *_: self.close()
            self.presenter.ClickRequested += self.click
            self.apply_regions()
            self.timer = Timer()
            self.timer.Interval = 67 if self.animation_active else 500
            self.timer.Tick += self.capture
            # Explicitly clear Chromium's page background as well as the
            # WebView background, including on runtimes with theme regressions.
            task = renderer.native.webview.CoreWebView2.CallDevToolsProtocolMethodAsync(
                'Emulation.setDefaultBackgroundColorOverride',
                '{"color":{"r":0,"g":0,"b":0,"a":0}}',
            )
            def ready(completed):
                if completed.IsFaulted:
                    logger.error('Transparent background override failed: %s', completed.Exception)
                if not self.closing:
                    self.timer.Start()
                    self.capture()
            task.ContinueWith(Action[Task[String]](ready), renderer.native.browser.syncContextTaskScheduler)

        def capture(self, *_):
            if self.busy or self.closing:
                return
            from System import Action
            from System.IO import MemoryStream
            from System.Threading.Tasks import Task
            from Microsoft.Web.WebView2.Core import CoreWebView2CapturePreviewImageFormat

            self.busy = True
            stream = MemoryStream()
            try:
                task = renderer.native.webview.CoreWebView2.CapturePreviewAsync(
                    CoreWebView2CapturePreviewImageFormat.Png, stream)
            except Exception:
                stream.Dispose()
                self.busy = False
                logger.exception('Could not capture overlay')
                return

            def present(completed):
                try:
                    if self.closing:
                        return
                    if completed.IsFaulted:
                        raise RuntimeError(str(completed.Exception))
                    pixels = stream.ToArray()
                    self.presenter.SetFrame(pixels)
                    if not self.presenter.Visible:
                        self.presenter.Show()
                    debug_path = os.environ.get('TARNISHED_OVERLAY_DEBUG_FRAME')
                    if debug_path and not self.debug_saved:
                        Path(debug_path).write_bytes(bytes(pixels))
                        self.debug_saved = True
                    if self.debug_frames_dir is not None and self.animation_active:
                        self.debug_frame_count += 1
                        if self.debug_frame_count in (1, 8, 16):
                            self.debug_frames_dir.mkdir(parents=True, exist_ok=True)
                            frame_path = self.debug_frames_dir / f'overlay-frame-{self.debug_frame_count:03d}.png'
                            frame_path.write_bytes(bytes(pixels))
                            logger.info('Saved diagnostic animation frame %s', self.debug_frame_count)
                    if not getattr(self, 'first_frame_logged', False):
                        logger.info('Overlay rendered: %s x %s, corner alpha %s',
                                    self.presenter.LastWidth, self.presenter.LastHeight,
                                    self.presenter.AlphaAt(0, 0))
                        self.first_frame_logged = True
                except Exception:
                    logger.exception('Could not present overlay')
                finally:
                    stream.Dispose()
                    self.busy = False
            task.ContinueWith(Action[Task](present), renderer.native.browser.syncContextTaskScheduler)

        def shutdown(self):
            self.closing = True
            if self.timer is not None:
                self.timer.Stop()
                self.timer.Dispose()
            if self.presenter is not None and not self.presenter.IsDisposed:
                self.presenter.Close()

    controller = Controller()
    renderer.expose(controller.resize, controller.close, controller.set_animation_active,
                    controller.set_interactive_regions, controller.export_speedrun)
    renderer.events.before_show += controller.before_show
    renderer.events.loaded += controller.loaded
    renderer.events.closing += controller.shutdown
    if owner_closed is not None:
        def close_with_owner():
            owner_closed.wait()
            # pywebview.destroy waits for the window and marshals to its UI
            # thread. A daemon waiter cannot keep a manually closed UI alive.
            controller.close()
        threading.Thread(target=close_with_owner, daemon=True).start()
    webview.start(gui='edgechromium')

