import sys

from PyQt5.QtCore import QTimer, QEventLoop
from PyQt5.QtWidgets import QApplication, QDialog, QHBoxLayout, QPushButton, QLineEdit

from asynker import Scheduler, Future, suspend


app = QApplication(sys.argv)
window = QDialog()
window.setLayout(QHBoxLayout())
edit = QLineEdit()
window.layout().addWidget(edit)
button = QPushButton('Click me')
window.layout().addWidget(button)


def signal(sig):
    def emitted(*args):
        sig.disconnect(emitted)
        future.set_result(args)
    future = Future()
    sig.connect(emitted)
    return future


async def dialogue():
    await signal(button.clicked)
    edit.setText('Type something here.')
    await signal(edit.editingFinished)
    button.setText('Very good.')

    timer = QTimer()
    timer.setSingleShot(True)
    timer.start(1500)
    await signal(timer.timeout)
    button.setText('Click me again to quit.')
    await signal(button.clicked)
    window.hide()


scheduler = Scheduler()
scheduler.run(dialogue())
window.show()

# This is the event loop. The quit condition is quite simply the window being closed.
while window.isVisible():
    scheduler.tick()
    app.processEvents(QEventLoop.AllEvents | QEventLoop.WaitForMoreEvents)
