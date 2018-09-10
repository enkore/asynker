"""
This examples shows how subprocess management using Qt's QProcess could be approached.
This received very little testing and would need a bit of work to be really useful,
but as an example in the vein of "this is probably the right way" it still serves its purpose.
"""

import sys

from PyQt5.QtCore import QProcess, QCoreApplication, QEventLoop

import asynker
from asynker import Future


class AsyncProcessError(RuntimeError):
    def __str__(self):
        return 'AsyncProcessError code %d' % self.args


class AsyncProcess:
    def __init__(self, args=None, qprocess=None, scheduler=None):
        self._scheduler = scheduler
        if qprocess:
            self._process = qprocess
            assert not args
        else:
            self._process = QProcess()
            self._process.setProgram(args[0])
            self._process.setArguments(args[1:])

        self._process.errorOccurred.connect(self._error_outside_await)
        self._stored_error = None

    def _error_outside_await(self, error):
        self._stored_error = error

    def _error_handling_future(self, source_signal, result_callback, exit_callback=None) -> Future:
        def error_occurred(error):
            fut.set_exception(AsyncProcessError(error))

        def process_finished(*args):
            exit_callback()

        def disconnect(fut):
            source_signal.disconnect(result_callback)
            if exit_callback:
                self._process.finished.disconnect(process_finished)
            self._process.errorOccurred.disconnect(error_occurred)
            self._process.errorOccurred.connect(self._error_outside_await)

        fut = asynker.Future(self._scheduler)
        source_signal.connect(result_callback)
        if exit_callback:
            self._process.finished.connect(process_finished)

        self._process.errorOccurred.disconnect(self._error_outside_await)
        self._process.errorOccurred.connect(error_occurred)
        fut.add_done_callback(disconnect)

        # Check if there already happened an error
        if self._stored_error is not None:
            error_occurred(self._stored_error)
            self._stored_error = None

        return fut

    def start(self) -> Future:
        def started():
            fut.set_result(self._process.processId())

        assert self._process.state() == QProcess.NotRunning
        fut = self._error_handling_future(self._process.started, started)
        self._process.start()
        return fut

    def read_stdout(self) -> Future:
        def data_available():
            fut.set_result(self._process.readAllStandardOutput())

        fut = self._error_handling_future(self._process.readyReadStandardOutput, data_available, data_available)
        return fut

    def read_stderr(self) -> Future:
        def data_available():
            fut.set_result(self._process.readAllStandardError())

        fut = self._error_handling_future(self._process.readAllStandardError, data_available, data_available)
        return fut

    def finish(self) -> Future:
        def finished(exit_code, exit_status):
            fut.set_result((exit_code, exit_status))

        fut = self._error_handling_future(self._process.finished, finished)
        if self._process.state() == QProcess.NotRunning:
            finished(self._process.exitCode(), self._process.exitStatus())
        return fut

    def running(self):
        return self._process.state() == QProcess.Running


async def run_ls():
    process = AsyncProcess(['ls', '-l', '/'], scheduler=scheduler)
    pid = await process.start()
    print('Subprocess pid', pid)
    while process.running():
        print((await process.read_stdout()).data().decode(), end='')
    exit_code, exit_status = await process.finish()
    print('Subprocess exit code', exit_code)


async def run_error():
    process = AsyncProcess(['you-dont-have-this-binary'], scheduler=scheduler)
    try:
        await process.start()
    except AsyncProcessError as ape:
        print('run_error:', ape)


if __name__ == '__main__':
    app = QCoreApplication(sys.argv)
    done = False

    def quit():
        global done
        done = True

    scheduler = asynker.Scheduler()

    examples = asynker.gather(run_ls(), run_error(), scheduler=scheduler)
    examples.add_done_callback(lambda _: quit())

    while not done:
        scheduler.tick()
        app.processEvents(QEventLoop.AllEvents | QEventLoop.WaitForMoreEvents)

    examples.result()
