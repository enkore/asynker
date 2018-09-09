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


def wait_for(ms):
    future = Future()
    timer = QTimer()
    timer.timeout.connect(lambda: (future.set_result(None), timer.deleteLater()))
    timer.setSingleShot(True)
    timer.start(ms)
    return future


async def waiterA():
    for n in range(5):
        await wait_for(500)
        print('waiterA', n)


async def waiterB():
    for n in range(10):
        await wait_for(100)
        print('waiterB', n)


async def waiterC():
    await wait_for(3000)
    print('Quitting.')
    quit()


scheduler = Scheduler()
scheduler.run(waiterA())
scheduler.run(waiterB())
scheduler.run(waiterC())

# This is the "event loop"
while not done:
    scheduler.tick()
    app.processEvents(QEventLoop.AllEvents | QEventLoop.WaitForMoreEvents)
