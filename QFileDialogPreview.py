import PyQt5.QtCore
import PyQt5.QtGui
import PyQt5.QtWidgets
import sys

class QFileDialogPreview(PyQt5.QtWidgets.QFileDialog):

    def __init__(self, *args, **kwargs):
        PyQt5.QtWidgets.QFileDialog.__init__(self, *args, **kwargs)
        self.setOption(PyQt5.QtWidgets
                      .QFileDialog.DontUseNativeDialog, True)
        self.preview = PyQt5.QtWidgets.QLabel('preview', self)
        self.preview.setFixedSize(250, 250)
        self.preview.setAlignment(PyQt5.QtCore.Qt.AlignCenter)
        layout = PyQt5.QtWidgets.QVBoxLayout()
        layout.addWidget(self.preview)
        layout.addStretch()
        self.layout().addLayout(layout, 1, 3, 1, 1)
        self.currentChanged.connect(self.on_change)
        self.fileSelected.connect(self.on_file_selected)
        self._file_selected = None

    def on_change(self, path):
        pixmap = PyQt5.QtGui.QPixmap(path)
        if(pixmap.isNull()):
            self.preview.setText('preview')
        else:
            self.preview.setPixmap(pixmap.scaled(
                self.preview.width(),
                self.preview.height(),
                PyQt5.QtCore.Qt.KeepAspectRatio,
                PyQt5.QtCore.Qt.SmoothTransformation
            ))

    def on_file_selected(self, file_):
        self._file_selected = file_

def open_(caption, directory, filter_):
    app = PyQt5.QtWidgets.QApplication(sys.argv)
    dialog = QFileDialogPreview(
                   caption=caption,
                 directory=directory,
                    filter=filter_
             )
    dialog.show()
    app.exec()
    return dialog._file_selected