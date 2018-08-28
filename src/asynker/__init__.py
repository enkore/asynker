import collections
import enum
import inspect
import types


class FutureState(enum.Enum):
    # Todo CANCELLED
    PENDING = 'pending'
    FINISHED = 'finished'


class Future:
    _state: FutureState = FutureState.PENDING
    _result = None
    _exception = None
    _scheduler = None

    def __init__(self, scheduler=None):
        self._scheduler = scheduler
        self._done_callbacks = []

    def done(self):
        """
        A future is done if it (1) finished (with a result or exception) (2) was cancelled.
        """
        return self._state != FutureState.PENDING

    def result(self):
        assert self._state == FutureState.FINISHED
        if self._exception is not None:
            raise self._exception
        return self._result

    def exception(self):
        assert self._state == FutureState.FINISHED
        return self._exception

    def add_done_callback(self, fn):
        """
        Add callback *fn* that will be run when the future enters a done state.

        The callback receives the futures as its sole argument.
        """
        if self._state != FutureState.PENDING:
            fn(self)
        else:
            self._done_callbacks.append(fn)

    def set_result(self, result):
        assert self._state == FutureState.PENDING
        self._state = FutureState.FINISHED
        self._result = result
        self._schedule_callbacks()

    def set_exception(self, exception):
        if isinstance(exception, type):
            exception = exception()
        self._state = FutureState.FINISHED
        self._exception = exception
        self._schedule_callbacks()

    def _schedule_callbacks(self):
        for cb in self._done_callbacks:
            self._scheduler.call_soon(cb, self)

    def _tick(self):
        pass

    def __await__(self):
        if not self.done():
            yield self
        return self.result()


class Task(Future):
    def __init__(self, coroutine, scheduler):
        super().__init__(scheduler)
        self._coroutine = coroutine

    def _tick(self, source_future=None):
        if source_future:
            exc = source_future.exception()
            value = source_future._result
        else:
            exc = value = None

        try:
            if exc is not None:
                self._coroutine.throw(exc)
            else:
                result = self._coroutine.send(value)
        except StopIteration as si:
            self.set_result(si.value)
        except Exception as exc:
            self.set_exception(exc)
        else:
            if isinstance(result, Future):
                result._scheduler = self._scheduler
                result.add_done_callback(lambda src: self._scheduler._queue_task(self, src))
            elif inspect.iscoroutine(result):
                f = ensure_future(result, self)
                f.add_done_callback(lambda src: self._scheduler._queue_task(self, src))
            else:
                self._scheduler._queue_task(self)


def ensure_future(future_or_coroutine, scheduler):
    if inspect.iscoroutine(future_or_coroutine):
        return Task(future_or_coroutine, scheduler)
    future_or_coroutine._scheduler = scheduler
    return future_or_coroutine


@types.coroutine
def suspend():
    yield


class Scheduler:
    def __init__(self):
        self._queue = collections.deque()
        self._blocked = []

    def tick(self):
        while self._queue:
            cb, args = self._queue.popleft()
            cb(*args)

    def run_until_complete(self, future_or_coroutine):
        future = ensure_future(future_or_coroutine, self)
        self._queue_task(future)
        while not future.done():
            self.tick()
        return future.result()

    def run(self, future_or_coroutine):
        future = ensure_future(future_or_coroutine, self)
        self._queue_task(future)
        return future

    def call_soon(self, cb, *args):
        self._queue.append((cb, args))

    def _queue_task(self, task_future, src=None):
        self._queue.append((task_future._tick, (src,)))
