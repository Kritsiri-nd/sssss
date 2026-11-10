Set ws = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
desktop = ws.SpecialFolders("Desktop")

Sub CreateLink(destPath)
    On Error Resume Next
    Set s = ws.CreateShortcut(destPath)
    s.TargetPath = "pythonw.exe"
    s.Arguments = """" & scriptDir & "\shopee_all_in_one_app.py"""
    s.WorkingDirectory = scriptDir
    s.IconLocation = scriptDir & "\scrcpy-5.0.1\scrcpy-win64-v5.0.1\scrcpy.exe,0"
    s.Description = "Shopee Video Auto-Poster Pro All-in-One Studio"
    s.Save
    On Error GoTo 0
End Sub

CreateLink desktop & "\Shopee Poster Studio.lnk"
CreateLink desktop & "\SHOPEE_POSTER_STUDIO.lnk"
