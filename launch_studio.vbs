Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "D:\Dev\ComfyUI\tools\shopee_poster"

On Error Resume Next
WshShell.Run "taskkill /F /IM scrcpy.exe", 0, True
On Error GoTo 0

WshShell.Run "pythonw.exe ""D:\Dev\ComfyUI\tools\shopee_poster\shopee_all_in_one_app.py""", 0, False

