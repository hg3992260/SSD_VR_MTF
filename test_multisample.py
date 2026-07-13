import sys
import os
pv_packages_dir = r'C:\Users\chris\Desktop\SSD+VR\pv_packages'
sys.path.insert(0, pv_packages_dir)
pyqt5_qt5_bin = os.path.join(pv_packages_dir, 'PyQt5', 'Qt5', 'bin')
pyqt5_root = os.path.join(pv_packages_dir, 'PyQt5')
if hasattr(os, 'add_dll_directory'):
    os.add_dll_directory(pyqt5_qt5_bin)
    os.add_dll_directory(pyqt5_root)
    os.add_dll_directory(pv_packages_dir)
from PySide6 import QtWidgets
import vtk
from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor
app = QtWidgets.QApplication(sys.argv)
win = QtWidgets.QMainWindow()
v = QVTKRenderWindowInteractor(win)
rw = v.GetRenderWindow()
rw.SetMultiSamples(0)
r = vtk.vtkRenderer()
rw.AddRenderer(r)
win.setCentralWidget(v)
win.show()
print('OK')
sys.exit(0)
