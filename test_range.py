import sys
from PySide6 import QtWidgets, QtCore, QtGui

class RangeSlider(QtWidgets.QWidget):
    valueChanged = QtCore.Signal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.minimum = -1000
        self.maximum = 3000
        self._lower = 300
        self._upper = 1500
        self._handle_radius = 8
        self._active_handle = None
        self._drag_offset = 0
        self.setFixedHeight(30)
        
    def setRange(self, min_val, max_val):
        self.minimum = min_val
        self.maximum = max_val
        self.update()
        
    def setValues(self, lower, upper):
        self._lower = max(self.minimum, min(lower, self.maximum))
        self._upper = max(self.minimum, min(upper, self.maximum))
        self.update()
        self.valueChanged.emit(int(self._lower), int(self._upper))
        
    def getValues(self):
        return int(self._lower), int(self._upper)
        
    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        
        w = self.width()
        h = self.height()
        r = self._handle_radius
        
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(QtGui.QColor(200, 200, 200))
        painter.drawRoundedRect(r, h//2 - 2, w - 2*r, 4, 2, 2)
        
        lx = self._val_to_pos(self._lower)
        ux = self._val_to_pos(self._upper)
        
        painter.setBrush(QtGui.QColor(0, 120, 215))
        painter.drawRoundedRect(QtCore.QRectF(lx, h//2 - 2, ux - lx, 4), 2, 2)
        
        painter.setPen(QtGui.QColor(150, 150, 150))
        painter.setBrush(QtGui.QColor(255, 255, 255))
        painter.drawEllipse(QtCore.QPointF(lx, h//2), r, r)
        painter.drawEllipse(QtCore.QPointF(ux, h//2), r, r)
        
    def _val_to_pos(self, val):
        w = self.width() - 2 * self._handle_radius
        return self._handle_radius + w * (val - self.minimum) / (self.maximum - self.minimum)
        
    def _pos_to_val(self, x):
        w = self.width() - 2 * self._handle_radius
        val = self.minimum + (x - self._handle_radius) / w * (self.maximum - self.minimum)
        return max(self.minimum, min(self.maximum, val))
        
    def mousePressEvent(self, event):
        x = event.pos().x()
        lx = self._val_to_pos(self._lower)
        ux = self._val_to_pos(self._upper)
        
        if abs(x - lx) < self._handle_radius * 2:
            self._active_handle = 'lower'
        elif abs(x - ux) < self._handle_radius * 2:
            self._active_handle = 'upper'
        elif lx < x < ux:
            self._active_handle = 'center'
            self._drag_offset = x
            self._drag_lower_start = self._lower
            self._drag_upper_start = self._upper
        else:
            self._active_handle = None

    def mouseMoveEvent(self, event):
        if not self._active_handle:
            return
        x = event.pos().x()
        val = self._pos_to_val(x)
        
        if self._active_handle == 'lower':
            self._lower = min(val, self._upper - 1)
        elif self._active_handle == 'upper':
            self._upper = max(val, self._lower + 1)
        elif self._active_handle == 'center':
            delta_val = self._pos_to_val(x) - self._pos_to_val(self._drag_offset)
            new_lower = self._drag_lower_start + delta_val
            new_upper = self._drag_upper_start + delta_val
            
            if new_lower < self.minimum:
                diff = self.minimum - new_lower
                new_lower += diff
                new_upper += diff
            elif new_upper > self.maximum:
                diff = new_upper - self.maximum
                new_lower -= diff
                new_upper -= diff
                
            self._lower = new_lower
            self._upper = new_upper
            
        self.update()
        self.valueChanged.emit(int(self._lower), int(self._upper))
        
    def mouseReleaseEvent(self, event):
        self._active_handle = None

if __name__ == '__main__':
    app = QtWidgets.QApplication(sys.argv)
    w = RangeSlider()
    w.show()
    QtCore.QTimer.singleShot(500, app.quit)
    app.exec()
    print("RangeSlider works")
