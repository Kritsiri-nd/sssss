"""Send absolute taps through scrcpy 5.0.1's UHID control channel."""
import argparse
import os
from pathlib import Path
import socket
import struct
import subprocess
import time
import secrets

FLAGS_NO_WINDOW = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0x08000000


DESCRIPTOR = bytes.fromhex(
    "05 0d 09 04 a1 01 09 22 a1 02"
    "09 42 15 00 25 01 75 01 95 01 81 02"
    "75 07 95 01 81 03 09 51 15 00 25 7f 75 08 95 01 81 02"
    "05 01 09 30 09 31 15 00 26 ff 7f 75 10 95 02 81 02 c0"
    "05 0d 09 54 15 00 25 01 75 08 95 01 81 02 c0"
)
MOUSE = bytes.fromhex(
    "05 01 09 02 a1 01 09 01 a1 00 05 09 19 01 29 01"
    "15 00 25 01 95 01 75 01 81 02 95 01 75 07 81 03"
    "05 01 09 30 09 31 15 81 25 7f 75 08 95 02 81 06 c0 c0"
)


class TouchSession:
    """Keep one scrcpy control connection open for a sequence of phone actions."""

    def __init__(self, adb="adb"):
        self.adb = adb
        self.process = None
        self.connection = None
        self.port = None
        self.remote = "/data/local/tmp/shopee-touch-server.jar"
        self.scid = f"{secrets.randbits(31):08x}"

    def __enter__(self):
        server = Path(__file__).parent / "scrcpy-5.0.1/scrcpy-win64-v5.0.1/scrcpy-server"
        subprocess.run([self.adb, "push", str(server), self.remote], check=True, creationflags=FLAGS_NO_WINDOW)
        self.port = subprocess.check_output(
            [self.adb, "forward", "tcp:0", f"localabstract:scrcpy_{self.scid}"], text=True, creationflags=FLAGS_NO_WINDOW
        ).strip()
        self.process = subprocess.Popen([
            self.adb, "shell", f"CLASSPATH={self.remote}", "app_process", "/",
            "com.genymobile.scrcpy.Server", "5.0.1", f"scid={self.scid}",
            "tunnel_forward=true", "video=false", "audio=false", "control=true",
            "send_device_meta=false", "send_dummy_byte=true", "log_level=debug",
        ], creationflags=FLAGS_NO_WINDOW)
        for _ in range(30):
            try:
                self.connection = socket.create_connection(("127.0.0.1", int(self.port)), 1)
                if self.connection.recv(1) == b"\0":
                    break
                self.connection.close()
                self.connection = None
            except OSError:
                pass
            time.sleep(0.15)
        else:
            self.close()
            raise RuntimeError("scrcpy control channel did not start")

        name = b"Shopee Touch"
        self.connection.sendall(
            struct.pack(">BHHHB", 12, 1, 0, 0, len(name))
            + name + struct.pack(">H", len(DESCRIPTOR)) + DESCRIPTOR
        )
        time.sleep(0.5)
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def close(self):
        if self.connection is not None:
            try:
                self.connection.close()
            except OSError:
                pass
            self.connection = None
        if self.process is not None:
            self.process.terminate()
            self.process.wait()
            self.process = None
        if self.port is not None:
            subprocess.run([self.adb, "forward", "--remove", f"tcp:{self.port}"], check=False, creationflags=FLAGS_NO_WINDOW)
            self.port = None

    def _send_touch(self, pressed, x, y):
        report = struct.pack("<BBHHB", pressed, 0, round(x * 32767), round(y * 32767), pressed)
        self.connection.sendall(struct.pack(">BHH", 13, 1, len(report)) + report)

    def tap(self, x, y):
        self._send_touch(1, x, y)
        time.sleep(0.10)
        self._send_touch(0, x, y)
        time.sleep(0.15)

    def swipe(self, x, y, end_x, end_y):
        self._send_touch(1, x, y)
        for i in range(1, 13):
            self._send_touch(1, x + (end_x - x) * i / 12, y + (end_y - y) * i / 12)
            time.sleep(0.025)
        self._send_touch(0, end_x, end_y)
        time.sleep(0.15)

    def clipboard(self, value):
        data = value.encode("utf-8")
        self.connection.sendall(struct.pack(">BQBI", 9, 0, 0, len(data)) + data)
        time.sleep(0.35)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("x", type=float, help="Horizontal position from 0 to 1")
    parser.add_argument("y", type=float, help="Vertical position from 0 to 1")
    parser.add_argument("--mouse-probe", action="store_true", help="Move the virtual mouse from the top-left corner without clicking")
    parser.add_argument("--mouse-click", action="store_true", help="Click after moving the virtual mouse")
    parser.add_argument("--clipboard", type=Path, help="Set Android clipboard from a UTF-8 text file")
    parser.add_argument("--swipe-to", nargs=2, type=float, metavar=("X", "Y"))
    args = parser.parse_args()
    if not (0 <= args.x <= 1 and 0 <= args.y <= 1):
        parser.error("Coordinates must be between 0 and 1")

    adb = os.environ.get("ADB", "adb")
    server = Path(__file__).parent / "scrcpy-5.0.1/scrcpy-win64-v5.0.1/scrcpy-server"
    remote = "/data/local/tmp/shopee-touch-server.jar"
    scid = secrets.token_hex(4)
    scid = f"{int(scid, 16) & 0x7fffffff:08x}"
    subprocess.run([adb, "push", str(server), remote], check=True, creationflags=FLAGS_NO_WINDOW)
    port = subprocess.check_output(
        [adb, "forward", "tcp:0", f"localabstract:scrcpy_{scid}"], text=True, creationflags=FLAGS_NO_WINDOW
    ).strip()
    process = None
    try:
        process = subprocess.Popen([
            adb, "shell", f"CLASSPATH={remote}", "app_process", "/",
            "com.genymobile.scrcpy.Server", "5.0.1", f"scid={scid}",
            "tunnel_forward=true", "video=false", "audio=false", "control=true",
            "send_device_meta=false", "send_dummy_byte=true", "log_level=debug",
        ], creationflags=FLAGS_NO_WINDOW)
        for _ in range(30):
            try:
                connection = socket.create_connection(("127.0.0.1", int(port)), 1)
                if connection.recv(1) == b"\0":
                    break
                connection.close()
            except OSError:
                pass
            time.sleep(0.15)
        else:
            raise RuntimeError("scrcpy control channel did not start")

        with connection:
            if args.clipboard:
                data = args.clipboard.read_text(encoding="utf-8-sig").strip().encode("utf-8")
                connection.sendall(struct.pack(">BQBI", 9, 0, 0, len(data)) + data)
                time.sleep(0.5)
                return
            name = b"Shopee Touch"
            descriptor = MOUSE if args.mouse_probe or args.mouse_click else DESCRIPTOR
            connection.sendall(
                struct.pack(">BHHHB", 12, 1, 0, 0, len(name))
                + name + struct.pack(">H", len(descriptor)) + descriptor
            )
            time.sleep(1)
            if args.mouse_probe or args.mouse_click:
                def move(dx, dy, button=0):
                    report = struct.pack("<Bbb", button, dx, dy)
                    connection.sendall(struct.pack(">BHH", 13, 1, len(report)) + report)
                    time.sleep(0.02)

                for _ in range(40):
                    move(-127, -127)
                dx, dy = round(args.x * 1216), round(args.y * 2720)
                while dx or dy:
                    step_x, step_y = min(dx, 12), min(dy, 12)
                    move(step_x, step_y)
                    dx -= step_x
                    dy -= step_y
                time.sleep(1)
                state = subprocess.check_output([adb, "shell", "dumpsys", "input"], text=True, errors="replace", creationflags=FLAGS_NO_WINDOW)
                lines = state.splitlines()
                for index, line in enumerate(lines):
                    if "MousePointerControllers:" in line:
                        print("\n".join(lines[index:index + 22]))
                if args.mouse_click:
                    move(0, 0, 1)
                    time.sleep(0.1)
                    move(0, 0)
                    time.sleep(0.5)
                return
            diagnostics = subprocess.check_output([adb, "shell", "dumpsys", "input"], text=True, errors="replace", creationflags=FLAGS_NO_WINDOW)
            lines = diagnostics.splitlines()
            for index, line in enumerate(lines):
                if "Shopee Touch" in line:
                    print("\n".join(lines[index:index + 32]))
            positions = [(1, args.x, args.y)]
            end_x, end_y = args.swipe_to or (args.x, args.y)
            if args.swipe_to:
                if not (0 <= end_x <= 1 and 0 <= end_y <= 1):
                    parser.error("Swipe endpoint must be between 0 and 1")
                positions.extend((1, args.x + (end_x - args.x) * i / 12,
                                  args.y + (end_y - args.y) * i / 12) for i in range(1, 13))
            positions.append((0, end_x, end_y))
            for pressed, x, y in positions:
                report = struct.pack("<BBHHB", pressed, 0, round(x * 32767), round(y * 32767), pressed)
                connection.sendall(struct.pack(">BHH", 13, 1, len(report)) + report)
                time.sleep(0.025 if args.swipe_to else 0.15)
            connection.sendall(struct.pack(">BH", 14, 1))
    finally:
        if process is not None:
            process.terminate()
            process.wait()
        subprocess.run([adb, "forward", "--remove", f"tcp:{port}"], check=False, creationflags=FLAGS_NO_WINDOW)


if __name__ == "__main__":
    main()
