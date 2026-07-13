import sys
import vtk
from PySide6 import QtWidgets
from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor

app = QtWidgets.QApplication(sys.argv)
win = QtWidgets.QMainWindow()
widget = QVTKRenderWindowInteractor(win)
win.setCentralWidget(widget)
renderer = vtk.vtkRenderer()
render_window = widget.GetRenderWindow()

iren = render_window.GetInteractor()
iren.SetDesiredUpdateRate(30.0)
iren.SetStillUpdateRate(0.0001)

render_window.AddRenderer(renderer)
iren.SetInteractorStyle(vtk.vtkInteractorStyleTrackballCamera())

win.show()
iren.Initialize()
print(" Success without showEvent\)
