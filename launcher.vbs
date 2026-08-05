' CunSub Launcher - launch GUI launcher without console window (ASCII only)
Set fso = CreateObject("Scripting.FileSystemObject")
Set ws = CreateObject("WScript.Shell")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
ws.CurrentDirectory = dir
ws.Run "pythonw """ & dir & "\launcher.pyw""", 0, False
