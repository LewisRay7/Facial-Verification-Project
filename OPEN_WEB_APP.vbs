Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")

projectDir = files.GetParentFolderName(WScript.ScriptFullName)
batchPath = projectDir & "\START_WEB_APP.bat"

If files.FileExists(batchPath) Then
    shell.Run Chr(34) & batchPath & Chr(34), 1, False
Else
    MsgBox "The web app launcher could not be found.", vbExclamation, "EVS Web App"
End If
