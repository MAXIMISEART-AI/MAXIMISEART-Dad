Attribute VB_Name = "AutomatyzacjaRozliczen"
Option Explicit

' Adapter VBA uruchamia ten sam lokalny silnik co plik CMD.
' Umieść plik XLSM obok "Utwórz rozliczenia.cmd".

Public Sub UruchomRozliczenia()
    Dim picker As FileDialog
    Dim sourcePath As String
    Dim launcherPath As String
    Dim command As String
    Dim exitCode As Long
    Dim shell As Object
    Dim fileSystem As Object
    Dim file As Object

    Set picker = Application.FileDialog(msoFileDialogFilePicker)
    With picker
        .Title = "Wybierz plik zbiorczy rozliczenia"
        .AllowMultiSelect = False
        .Filters.Clear
        .Filters.Add "Pliki Excel", "*.xlsx"
        If .Show <> -1 Then Exit Sub
        sourcePath = .SelectedItems(1)
    End With

    Set fileSystem = CreateObject("Scripting.FileSystemObject")
    For Each file In fileSystem.GetFolder(ThisWorkbook.Path).Files
        If LCase$(file.Name) Like "utw?rz rozliczenia.cmd" Then
            launcherPath = file.Path
            Exit For
        End If
    Next file

    If launcherPath = vbNullString Then
        MsgBox "Nie znaleziono pliku Utwórz rozliczenia.cmd obok tego pliku XLSM.", vbExclamation
        Exit Sub
    End If

    command = "cmd.exe /c " & Chr(34) & QuoteArg(launcherPath) & " " & QuoteArg(sourcePath) & Chr(34)
    Set shell = CreateObject("WScript.Shell")
    exitCode = shell.Run(command, 0, True)

    Select Case exitCode
        Case 0
            MsgBox "Rozliczenia zostały przygotowane. Sprawdź pliki pracowników.", vbInformation
        Case 2
            MsgBox "Proces zakończył się z ostrzeżeniami. Sprawdź komunikaty i pliki pracowników.", vbExclamation
        Case Else
            MsgBox "Nie udało się przygotować rozliczeń. Kod procesu: " & exitCode, vbCritical
    End Select
End Sub

Private Function QuoteArg(ByVal value As String) As String
    QuoteArg = Chr(34) & Replace(value, Chr(34), Chr(34) & Chr(34)) & Chr(34)
End Function
