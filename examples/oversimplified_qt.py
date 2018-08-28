"""
This is a very simplified example showing how Asynker can be used in conjunction
with the Qt event loop.
"""

import sys

from PyQt5.QtCore import QCoreApplication, QObject, QTimer, QEventLoop
from asynker import Scheduler, Future, suspend


app = QCoreApplication(sys.argv)
done = False


def quit():
    global done
    done = True


class Timer(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)

    async def run_event_loop(self):
        timer = QTimer(self)
        timer.start(1000)
        while not done:
            await suspend()
            app.processEvents(QEventLoop.AllEvents | QEventLoop.WaitForMoreEvents)

    def wait(self, ms):
        future = Future()
        timer = QTimer(self)
        timer.timeout.connect(lambda: (future.set_result(None), timer.deleteLater()))
        timer.setSingleShot(True)
        timer.start(ms)
        return future


async def waiterA():
    for n in range(5):
        await timer.wait(500)
        print('waiterA', n)


async def waiterB():
    for n in range(10):
        await timer.wait(100)
        print('waiterB', n)


async def waiterC():
    await timer.wait(3000)
    print('Quitting.')
    quit()


timer = Timer()
scheduler = Scheduler()
scheduler.run(waiterA())
scheduler.run(waiterB())
scheduler.run(waiterC())
scheduler.run_until_complete(timer.run_event_loop())