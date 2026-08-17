' =============================================================================
' PURPOSE:
'   Start YTPM with no console / black CMD window.
'
' INTERNAL LOGIC:
'   1. Resolve this script's folder as the project root.
'   2. Seed .env from .env.example when missing.
'   3. Read YTPM_VENV from .env (default C:\PythonVenvs\venv).
'   4. Run Scripts\pythonw.exe -B ytpm_launch.pyw with WindowStyle 0 (hidden).
'      ytpm_launch.pyw installs missing deps then opens the GUI.
'
' EXAMPLE INVOCATION:
'   Double-click Run_YTPM.vbs
'   Expected: YTPM window only (no DOS prompt).
' =============================================================================

Option Explicit

Dim fso, sh, root, envPath, examplePath, venv, pyw, launch, line, parts, key, val
Dim ts

Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")

root = fso.GetParentFolderName(WScript.ScriptFullName)
If Right(root, 1) <> "\" Then root = root & "\"

envPath = root & ".env"
examplePath = root & ".env.example"
If Not fso.FileExists(envPath) Then
  If fso.FileExists(examplePath) Then
    fso.CopyFile examplePath, envPath
  End If
End If

venv = "C:\PythonVenvs\venv"
If fso.FileExists(envPath) Then
  Set ts = fso.OpenTextFile(envPath, 1)
  Do While Not ts.AtEndOfStream
    line = Trim(ts.ReadLine)
    If Len(line) > 0 And Left(line, 1) <> "#" Then
      parts = Split(line, "=", 2)
      If UBound(parts) >= 1 Then
        key = Trim(parts(0))
        val = Trim(parts(1))
        If Len(val) >= 2 Then
          If Left(val, 1) = """" And Right(val, 1) = """" Then
            val = Mid(val, 2, Len(val) - 2)
          End If
        End If
        If StrComp(key, "YTPM_VENV", vbTextCompare) = 0 And Len(val) > 0 Then
          venv = val
        End If
      End If
    End If
  Loop
  ts.Close
End If

If Right(venv, 1) = "\" Then venv = Left(venv, Len(venv) - 1)

pyw = venv & "\Scripts\pythonw.exe"
launch = root & "ytpm_launch.pyw"

If Not fso.FileExists(pyw) Then
  MsgBox "pythonw.exe not found:" & vbCrLf & pyw & vbCrLf & vbCrLf & _
         "Set YTPM_VENV in .env to your virtualenv root" & vbCrLf & _
         "(folder that contains Scripts\pythonw.exe).", _
         vbCritical, "YouTube Playlist Manager"
  WScript.Quit 1
End If

If Not fso.FileExists(launch) Then
  MsgBox "Missing launch script:" & vbCrLf & launch, vbCritical, "YouTube Playlist Manager"
  WScript.Quit 1
End If

sh.CurrentDirectory = Left(root, Len(root) - 1)
' 0 = hidden window, False = do not wait (GUI keeps running after this script exits)
sh.Run """" & pyw & """ -B """ & launch & """", 0, False
WScript.Quit 0
