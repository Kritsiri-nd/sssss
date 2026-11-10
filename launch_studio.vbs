Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = scriptDir

On Error Resume Next
WshShell.Run "taskkill /F /IM scrcpy.exe", 0, True
On Error GoTo 0

WshShell.Run "pythonw.exe """ & scriptDir & "\shopee_all_in_one_app.py""", 0, False

