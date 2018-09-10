"""
This example shows how subprocess management using Qt's QProcess could be approached.
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


class AsyncProcessLostWrite(RuntimeError):
    def __str__(self):
        return 'AsyncProcessLostWrite: process did not consume written data before exiting'


class AsyncProcess:
    """
    Wraps a QProcess and provides a neat await-able interface.

    This is not "cross-task-safe", i.e. one AsyncProcess should not be manipulated concurrently
    by more than one task.
    """

    def __init__(self, args=None, qprocess=None, scheduler=None):
        self._scheduler = scheduler
        if qprocess:
            self._process = qprocess
            assert not args
        else:
            self._process = QProcess()
            self._process.setProgram(args[0])
            self._process.setArguments(args[1:])

        self._current_error_occured = self._error_outside_await
        self._process.errorOccurred.connect(self._error_outside_await)
        self._stored_error = None

    def _error_outside_await(self, error):
        self._stored_error = error

    def _set_error_occured(self, swapin):
        swapout = self._current_error_occured
        self._process.errorOccurred.disconnect(swapout)
        self._process.errorOccurred.connect(swapin)
        self._current_error_occured = swapin

    def _error_handling_future(self, source_signal, result_callback, exit_callback=None) -> Future:
        """
        Create future responding to QProcess errors.

        *result_callback* is connected to *source_signal*. *exit_callback* is connected
        to QProcess.finished. Any error occurring until completion of the future will
        set an exception on the future and thus consume the error.

        Signal connections are undone when the future is done.
        """
        def error_occurred(error):
            fut.set_exception(AsyncProcessError(error))

        def process_finished(*args):
            exit_callback()

        def disconnect(fut):
            source_signal.disconnect(result_callback)
            if exit_callback:
                self._process.finished.disconnect(process_finished)
            self._set_error_occured(self._error_outside_await)

        fut = asynker.Future(self._scheduler)
        source_signal.connect(result_callback)
        if exit_callback:
            self._process.finished.connect(process_finished)
        self._set_error_occured(error_occurred)
        fut.add_done_callback(disconnect)

        # Check if there already happened an error
        if self._stored_error is not None:
            error_occurred(self._stored_error)
            self._stored_error = None

        return fut

    def start(self, mode=QProcess.ReadWrite) -> Future:
        """
        Start the process. *mode* is passed to QProcess.start().
        """
        def started():
            fut.set_result(self._process.processId())

        assert self._process.state() == QProcess.NotRunning
        fut = self._error_handling_future(self._process.started, started)
        self._process.start(mode)
        return fut

    def _read(self, ready_read_signal, read_method) -> Future:
        def data_available():
            fut.set_result(read_method().data())

        fut = self._error_handling_future(ready_read_signal, data_available, data_available)
        # Clear out buffered data immediately
        data = read_method().data()
        if data:
            fut.set_result(data)
        elif not data and self._process.state() == QProcess.NotRunning:
            fut.set_result(b'')
        return fut

    def read_stdout(self) -> Future:
        """
        Read some binary data from the process's stdout channel.
        """
        return self._read(self._process.readyReadStandardOutput, self._process.readAllStandardOutput)

    def read_stderr(self) -> Future:
        """
        Read some binary data from the process's stdout channel.
        """
        return self._read(self._process.readyReadStandardError, self._process.readAllStandardError)

    def write(self, data) -> Future:
        """
        Write *data* to the standard input of the attached process.
        """
        def bytes_written(n=None):
            nonlocal pending_bytes
            if n is None and pending_bytes:
                fut.set_exception(AsyncProcessLostWrite)
            elif n:
                pending_bytes -= n
            if not pending_bytes:
                fut.set_result(None)

        assert self._process.state() == QProcess.Running
        fut = self._error_handling_future(self._process.bytesWritten, bytes_written, bytes_written)

        pending_bytes = len(data)
        amount = self._process.write(data)
        if amount == -1:
            fut.set_exception(OSError)
        pending_bytes -= amount
        if not pending_bytes:
            fut.set_result(None)
        return fut

    def write_eof(self):
        """
        Close (send EOF to) the standard input of the attached process.
        """
        self._process.closeWriteChannel()

    def finish(self) -> Future:
        """
        Wait until the process exits. Returns an (exit_code, QProcess.ExitStatus) tuple.
        """
        def finished(exit_code, exit_status):
            fut.set_result((exit_code, exit_status))

        fut = self._error_handling_future(self._process.finished, finished)
        if self._process.state() == QProcess.NotRunning:
            finished(self._process.exitCode(), self._process.exitStatus())
        return fut

    def running(self):
        return self._process.state() == QProcess.Running


async def run_ls():
    print('--- Invoking ls -l / ---')
    process = AsyncProcess(['ls', '-l', '/'], scheduler=scheduler)
    pid = await process.start()
    print('Subprocess pid', pid)
    while process.running():
        print((await process.read_stdout()).decode(), end='')
    exit_code, exit_status = await process.finish()
    print('Subprocess exit code', exit_code)


async def run_error():
    print('--- Invoking a binary that does not exist ---')
    process = AsyncProcess(['you-dont-have-this-binary'], scheduler=scheduler)
    try:
        await process.start()
    except AsyncProcessError as ape:
        print('run_error:', ape)


async def run_grep_stderr():
    print('--- Invoking grep(1) with bad options ---')
    process = AsyncProcess(['grep', '-asdf'], scheduler=scheduler)
    await process.start()
    exit_code, exit_status = await process.finish()
    print('grep(1) bad options, exit code:', exit_code)
    print('grep(1) stderr:', (await process.read_stderr()).decode())
    assert await process.read_stderr() == b''  # Process finished, no more output, all fine.


async def run_gzip():
    print('-- Compressing something with gzip(1) ---')
    process = AsyncProcess(['gzip', '-9'], scheduler=scheduler)
    await process.start()

    await process.write(b'123456789' * 1000)
    process.write_eof()

    try:
        await process.write(b'1234')
    except AsyncProcessLostWrite as aplw:
        print('Write after EOF raises (as expected)', aplw)
    else:
        assert False

    gzipped = await process.read_stdout()
    print('gzipped 12345789 (hex):', gzipped.hex())

    await process.finish()


if __name__ == '__main__':
    app = QCoreApplication(sys.argv)
    done = False

    def quit():
        global done
        done = True

    scheduler = asynker.Scheduler()

    example1 = scheduler.run(run_ls())
    example2 = asynker.ensure_future(run_error(), scheduler)
    example3 = asynker.ensure_future(run_grep_stderr(), scheduler)
    example4 = asynker.ensure_future(run_gzip(), scheduler)

    example1.add_done_callback(lambda _: scheduler.run(example2))
    example2.add_done_callback(lambda _: scheduler.run(example3))
    example3.add_done_callback(lambda _: scheduler.run(example4))
    example4.add_done_callback(lambda _: quit())

    while not done:
        scheduler.tick()
        app.processEvents(QEventLoop.AllEvents | QEventLoop.WaitForMoreEvents)

    example1.result()
    example2.result()
    example3.result()
    example4.result()
