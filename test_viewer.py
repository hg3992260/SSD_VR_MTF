import sys
from PySide6 import QtWidgets
import ssd_vr_viewer
app = QtWidgets.QApplication(sys.argv)
win = ssd_vr_viewer.ViewerWindow()
win.show()
print('Window shown')

