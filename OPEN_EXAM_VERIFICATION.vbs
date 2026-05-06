Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")

projectDir = files.GetParentFolderName(WScript.ScriptFullName)
exePath = projectDir & "\dist\ExamVerificationSystem\ExamVerificationSystem.exe"
pythonPath = projectDir & "\.venv\Scripts\pythonw.exe"
scriptPath = projectDir & "\Desktop\desktop_app.py"

If files.FileExists(exePath) Then
    shell.Run Chr(34) & exePath & Chr(34), 1, False
ElseIf files.FileExists(pythonPath) And files.FileExists(scriptPath) Then
    shell.Run Chr(34) & pythonPath & Chr(34) & " " & Chr(34) & scriptPath & Chr(34), 1, False
Else
    MsgBox "Exam Verification System could not start." & vbCrLf & vbCrLf & _
        "Build the EXE with build_desktop_exe.bat or run setup.bat first.", _
        vbExclamation, "Exam Verification System"
End If
