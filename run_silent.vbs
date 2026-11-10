Set WshShell = CreateObject("WScript.Shell")
Dim cmd
cmd = ""
For i = 0 To WScript.Arguments.Count - 1
    cmd = cmd & " """ & WScript.Arguments(i) & """"
Next
WshShell.Run "cmd.exe /c """ & Mid(cmd, 2) & """", 0, False
