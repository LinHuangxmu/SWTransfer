Option Explicit

' Select one component before running this macro.
' Results are written to the VBA Immediate window (Ctrl+G).

Sub main()
    Dim swApp As SldWorks.SldWorks
    Dim swModel As SldWorks.ModelDoc2
    Dim swSelMgr As SldWorks.SelectionMgr
    Dim swComp As SldWorks.Component2

    Set swApp = Application.SldWorks
    Set swModel = swApp.ActiveDoc

    If swModel Is Nothing Then
        MsgBox "Open an assembly first."
        Exit Sub
    End If

    Set swSelMgr = swModel.SelectionManager
    Set swComp = swSelMgr.GetSelectedObjectsComponent4(1, -1)

    If swComp Is Nothing Then
        MsgBox "Select one component in the assembly first."
        Exit Sub
    End If

    Dim R1Status As Long, R1DirStatus As Long
    Dim R2Status As Long, R2DirStatus As Long
    Dim L1Status As Long, L2Status As Long
    Dim RPoint1 As Variant, RDir1 As Variant
    Dim RPoint2 As Variant, RDir2 As Variant
    Dim LDir1 As Variant, LDir2 As Variant
    Dim result As Long

    result = swComp.GetRemainingDOFs( _
        R1Status, RPoint1, R1DirStatus, RDir1, _
        R2Status, RPoint2, R2DirStatus, RDir2, _
        L1Status, LDir1, L2Status, LDir2)

    Debug.Print String(60, "=")
    Debug.Print "Component: " & swComp.Name2
    Debug.Print "IsFixed: " & CStr(swComp.IsFixed)
    Debug.Print "ReturnValue: " & CStr(result)
    Debug.Print "R1Status=" & R1Status & "; R1DirStatus=" & R1DirStatus
    DumpValue "RPoint1", RPoint1
    DumpValue "RDir1", RDir1
    Debug.Print "R2Status=" & R2Status & "; R2DirStatus=" & R2DirStatus
    DumpValue "RPoint2", RPoint2
    DumpValue "RDir2", RDir2
    Debug.Print "L1Status=" & L1Status
    DumpValue "LDir1", LDir1
    Debug.Print "L2Status=" & L2Status
    DumpValue "LDir2", LDir2
End Sub

Private Sub DumpValue(ByVal label As String, ByVal value As Variant)
    On Error GoTo failed

    Dim data As Variant
    If IsObject(value) Then
        data = value.ArrayData
    Else
        data = value
    End If

    If IsArray(data) Then
        Debug.Print label & ": [" & CStr(data(0)) & ", " & _
                    CStr(data(1)) & ", " & CStr(data(2)) & "]"
    Else
        Debug.Print label & ": " & CStr(data)
    End If
    Exit Sub

failed:
    Debug.Print label & ": NULL/UNREADABLE"
End Sub
