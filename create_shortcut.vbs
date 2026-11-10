Set ws = CreateObject("WScript.Shell")
desktop = ws.SpecialFolders("Desktop")

Sub CreateLink(destPath)
    On Error Resume Next
    Set s = ws.CreateShortcut(destPath)
    s.TargetPath = "pythonw.exe"
    s.Arguments = """D:\Dev\ComfyUI\tools\shopee_poster\shopee_all_in_one_app.py"""
    s.WorkingDirectory = "D:\Dev\ComfyUI\tools\shopee_poster"
    s.IconLocation = "D:\Dev\ComfyUI\tools\shopee_poster\scrcpy-5.0.1\scrcpy-win64-v5.0.1\scrcpy.exe,0"
    s.Description = "Shopee Video Auto-Poster Pro All-in-One Studio"
    s.Save
    On Error GoTo 0
End Sub

CreateLink desktop & "\Shopee Poster Studio.lnk"
CreateLink desktop & "\SHOPEE_POSTER_STUDIO.lnk"
