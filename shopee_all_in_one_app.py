"""Shopee Video Auto-Poster Pro - All-in-One Desktop Application.
Seamlessly unifies the Web Control Dashboard and Real-time Native 60 FPS scrcpy into a single window.
Uses a 2-column TableLayoutPanel to guarantee zero overlap between WebView2 and scrcpy.
"""
import sys
import os
import time
import subprocess
import threading
import ctypes
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).parent.resolve()
SCRCPY_EXE = BASE_DIR / "scrcpy-5.0.1" / "scrcpy-win64-v5.0.1" / "scrcpy.exe"
WEB_SERVER_SCRIPT = BASE_DIR / "shopee_web_server.py"
PYTHON_EXE = str(Path(sys.executable).with_name("pythonw.exe"))
if not Path(PYTHON_EXE).exists():
    PYTHON_EXE = sys.executable

# Add WebView2 Lib dynamically from installed webview package
try:
    import webview
    WEBVIEW_LIB = Path(webview.__file__).parent / "lib"
    if WEBVIEW_LIB.exists():
        sys.path.append(str(WEBVIEW_LIB))
except Exception:
    pass

import clr
clr.AddReference("System.Windows.Forms")
clr.AddReference("System.Drawing")
clr.AddReference("Microsoft.Web.WebView2.WinForms")

from System.Windows.Forms import (
    Application, Form, Panel, TableLayoutPanel, ColumnStyle, SizeType,
    DockStyle, FormWindowState, FormStartPosition, Padding
)
from System.Drawing import Size, Color
from Microsoft.Web.WebView2.WinForms import WebView2
import System.Threading as ST
import System

user32 = ctypes.windll.user32
FLAGS_NO_WINDOW = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0x08000000

def ensure_web_server():
    """Ensure the background HTTP server on port 8090 is running."""
    import urllib.request
    try:
        urllib.request.urlopen("http://127.0.0.1:8090/api/status", timeout=1.5)
        return
    except Exception:
        pass

    cmd = [PYTHON_EXE, str(WEB_SERVER_SCRIPT)]
    subprocess.Popen(cmd, creationflags=FLAGS_NO_WINDOW)
    for _ in range(15):
        try:
            time.sleep(0.3)
            urllib.request.urlopen("http://127.0.0.1:8090/api/status", timeout=1.5)
            break
        except Exception:
            pass

class ShopeeAllInOneApp(Form):
    def __init__(self):
        super().__init__()
        self.Text = "Shopee Video Auto-Poster Pro (Unified 60 FPS Studio)"
        self.Size = Size(1750, 960)
        self.BackColor = Color.FromArgb(15, 23, 42) # Slate-900
        self.StartPosition = FormStartPosition.CenterScreen
        self.WindowState = FormWindowState.Maximized

        # 2-Column TableLayoutPanel: Strictly isolates Dashboard and Phone to prevent overlapping
        self.tlp = TableLayoutPanel()
        self.tlp.Dock = DockStyle.Fill
        self.tlp.ColumnCount = 2
        self.tlp.RowCount = 1
        self.tlp.Padding = Padding(0)
        self.tlp.Margin = Padding(0)
        self.tlp.BackColor = Color.FromArgb(15, 23, 42)

        # Col 0: Dashboard (100% of remaining space)
        self.tlp.ColumnStyles.Add(ColumnStyle(SizeType.Percent, 100.0))
        # Col 1: Phone Frame (Fixed 455px for Xiaomi 12T 20:9 ratio)
        self.tlp.ColumnStyles.Add(ColumnStyle(SizeType.Absolute, 455.0))

        # Left: Edge WebView2 Dashboard Control
        self.webview = WebView2()
        self.webview.Dock = DockStyle.Fill
        self.webview.Margin = Padding(0)
        self.webview.CoreWebView2InitializationCompleted += self.on_webview_initialized
        self.tlp.Controls.Add(self.webview, 0, 0)

        # Right: Phone Container Panel
        self.scrcpy_panel = Panel()
        self.scrcpy_panel.Dock = DockStyle.Fill
        self.scrcpy_panel.Margin = Padding(0)
        self.scrcpy_panel.BackColor = Color.FromArgb(0, 0, 0)
        self.tlp.Controls.Add(self.scrcpy_panel, 1, 0)

        self.Controls.Add(self.tlp)

        self.scrcpy_proc = None
        self.scrcpy_hwnd = 0

        self.Shown += self.on_shown
        self.Resize += self.on_resize
        self.FormClosing += self.on_closing

    def on_shown(self, sender, args):
        # 1. Initialize WebView2 under STA thread
        try:
            self.webview.EnsureCoreWebView2Async(None)
        except Exception as e:
            print("EnsureCoreWebView2Async error:", e)

        # 2. Dock scrcpy
        threading.Thread(target=self.dock_scrcpy, daemon=True).start()

    def on_webview_initialized(self, sender, args):
        if args.IsSuccess:
            print("WebView2 initialized successfully. Navigating...")
            self.webview.CoreWebView2.Navigate("http://127.0.0.1:8090/?embedded=1")
        else:
            print("WebView2 initialization failed:", args.InitializationException)

    def dock_scrcpy(self):
        time.sleep(0.3)
        subprocess.run(["taskkill", "/F", "/IM", "scrcpy.exe"], capture_output=True, creationflags=FLAGS_NO_WINDOW)
        time.sleep(0.4)

        if not SCRCPY_EXE.exists():
            return

        cmd = [
            str(SCRCPY_EXE),
            "-s", "4HZHZDBAYTPBNZTW",
            "--window-title", "ShopeeEmbeddedScrcpy",
            "--window-borderless",
            "--no-audio"
        ]
        self.scrcpy_proc = subprocess.Popen(cmd, creationflags=FLAGS_NO_WINDOW)

        # Find HWND
        for _ in range(60):
            hwnd = user32.FindWindowW(None, "ShopeeEmbeddedScrcpy")
            if hwnd:
                self.scrcpy_hwnd = hwnd
                break
            time.sleep(0.15)

        if self.scrcpy_hwnd:
            time.sleep(0.2)
            parent_handle = self.scrcpy_panel.Handle.ToInt64()
            user32.SetParent(self.scrcpy_hwnd, parent_handle)

            # Style as child window with clipping enabled for DirectX/D3D11 rendering
            GWL_STYLE = -16
            WS_CHILD = 0x40000000
            WS_VISIBLE = 0x10000000
            WS_CLIPSIBLINGS = 0x04000000
            WS_CLIPCHILDREN = 0x02000000
            style = WS_CHILD | WS_VISIBLE | WS_CLIPSIBLINGS | WS_CLIPCHILDREN
            user32.SetWindowLongW(self.scrcpy_hwnd, GWL_STYLE, style)

            # Move and fit to right panel
            w = max(400, self.scrcpy_panel.ClientSize.Width)
            h = max(700, self.scrcpy_panel.ClientSize.Height)
            user32.MoveWindow(self.scrcpy_hwnd, 0, 0, w, h, True)
            user32.ShowWindow(self.scrcpy_hwnd, 5)  # SW_SHOW
            user32.SetWindowPos(self.scrcpy_hwnd, 0, 0, 0, w, h, 0x0064)  # SWP_FRAMECHANGED | SWP_SHOWWINDOW | SWP_NOZORDER
            print("scrcpy successfully docked into panel!")
        else:
            print("Failed to locate scrcpy window.")

    def on_resize(self, sender, args):
        if self.scrcpy_hwnd:
            w = max(400, self.scrcpy_panel.ClientSize.Width)
            h = max(700, self.scrcpy_panel.ClientSize.Height)
            user32.MoveWindow(self.scrcpy_hwnd, 0, 0, w, h, True)
            user32.SetWindowPos(self.scrcpy_hwnd, 0, 0, 0, w, h, 0x0064)

    def on_closing(self, sender, args):
        if self.scrcpy_proc:
            try:
                self.scrcpy_proc.terminate()
            except Exception:
                pass
        subprocess.run(["taskkill", "/F", "/IM", "scrcpy.exe"], capture_output=True, creationflags=FLAGS_NO_WINDOW)

def run_app():
    try:
        ensure_web_server()
        app = ShopeeAllInOneApp()
        Application.Run(app)
    except Exception as e:
        import traceback
        Path(r"D:\Dev\ComfyUI\tools\shopee_all_in_one_app.log").write_text(traceback.format_exc(), encoding="utf-8")

def main():
    try:
        t = ST.Thread(ST.ThreadStart(run_app))
        t.SetApartmentState(ST.ApartmentState.STA)
        t.Start()
        t.Join()
    except Exception as e:
        import traceback
        Path(r"D:\Dev\ComfyUI\tools\shopee_all_in_one_app.log").write_text(traceback.format_exc(), encoding="utf-8")

if __name__ == "__main__":
    main()
