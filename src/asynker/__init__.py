import collections
import enum
import inspect
import threading
import types


class FutureState(enum.Enum):
    PENDING = 'pending'
    FINISHED = 'finished'
    CANCELLED = 'cancelled'


class CancelledError(Exception):
    """Future/Task was cancelled."""


class Future:
    """
    A future represents the result of some computation that may become available in *drumroll* the future.

    A future starts out in PENDING state.

    Calling set_result(v) transitions it to FINISHED state and
    will resume dependent coroutines (i.e. those waiting on this Future)
    at the next Scheduler.tick().

    Calling set_exception(e) transitions it to FINISHED state as well
    and generally works the same way as set_result(), but instead
    of providing a value to dependent coroutines, they will blow
    up with an exception.

    result() retrieves the current result *or* raises the set exception;
    ``x = await future()`` is semantically equivalent to
    ``twiddle_thumbs_until(future.is.done); x = future.result()``.
    """
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

    def cancel(self):
        self._state = FutureState.CANCELLED
        return True

    def cancelled(self):
        return self._state == FutureState.CANCELLED

    def result(self):
        assert self.done()
        if self._exception is not None:
            raise self._exception
        return self._result

    def exception(self):
        assert self.done()
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
    """
    A Task is a concretisation  of the Future concept;
    it represents a thread (no, wait, loaded word)... uhm...
    a *line* (fiber? oops...) of execution.

    In other words, a Task object corresponds to a coroutine *invocation*
    (the terminology is pretty loose here, in Python's terms, "async_foo()" *is* a coroutine),
    so it is a concrete computation that can be advanced in response to Futures finishing.

    The result() of a Task is the ``return`` value of the coroutine it represents.
    """

    def __init__(self, coroutine, scheduler):
        super().__init__(scheduler)
        self._coroutine = coroutine
        self._cancel = False
        self._waits_on_future = None

    def cancel(self):
        if self.done():
            return False
        self._cancel = True
        return True

    def _tick(self, source_future=None):
        # source_future is "what send us here",
        # i.e. the coroutine awaited some future and
        # *now* that future is completed and called source_future.
        if source_future:
            exc = source_future.exception()
            value = source_future._result
        else:
            exc = value = None

        if self._cancel:
            # When we are asked to cancel the execution of the coroutine, we inject
            # a CancelledError exception at the next yield point of the coroutine.
            # This overrides prior exceptions.
            # Handling a CancelledError swallows any result you could've gotten out of an await/yield.
            # So... you probably don't want to do that.
            exc = CancelledError()
            self._cancel = False

        # We're running so we can't possibly be waiting on a future.
        self._waits_on_future = None

        try:
            if exc is not None:
                # Inject the exception into the coroutine at the await-point.
                # This can/will trigger the exception stack to wind up,
                # stuff like exception handling and context managers can now happen
                # in the coroutine.
                result = self._coroutine.throw(exc)
            else:
                # Return the value provided by the future to the coroutine,
                # i.e. .send(v) makes the "await" expression return "v".
                result = self._coroutine.send(value)
        except StopIteration as si:
            # This means the coroutine has returned and is now done.
            if self._cancel:
                # A "late" cancellation, this can pretty much only happen if a coroutine cancels itself
                # after the last yield point in the current control flow path.
                self.set_exception(CancelledError())
                self._state = FutureState.CANCELLED
            else:
                self.set_result(si.value)
        except CancelledError as ce:
            self.set_exception(ce)
            self._state = FutureState.CANCELLED
        except Exception as exc:
            self.set_exception(exc)
        else:
            # "result" can be a couple of things.
            # Basically, every "await" works like a "yield" in the sense that it returns
            # whatever was handed to it back to whoever is one level above in the stack.
            # That "whoever is one level above in the stack" is *us* -- we invoked the
            # coroutine above.
            #
            # So, "foo = await async_bar()" will hand us the async_bar() coroutine-instance-thing
            # (I'd call "async_bar" the coroutine here and async_bar() is an invocation of a it).
            # In this case, we want to schedule that coroutine.
            #
            # "foo = await some_future" (which can look the same as above,
            # e.g. "await some_regular_function_RETURNING_a_future()") will hand us some_future.
            #
            # In either case we'll simply resume the current coroutine invocation once
            # the invoked coroutine / some_future has completed. Either is handled
            # by converting it to a future first (if necessary) and adding a done callback
            # to it enqueuing the current coroutine.
            #
            # The third case is we get some arbitrary value. This just means that somewhere
            # a bare yield/await happened (e.g. suspend() is a case of this),
            # which bubbles the value up to us as usual.
            # In that case we immediately re-queue the current coroutine
            # because it can continue at least another iteration.
            if isinstance(result, Future):
                result._scheduler = self._scheduler
                self._wait_on_future(result)
            elif inspect.iscoroutine(result):
                f = ensure_future(result, self)
                self._wait_on_future(f)
            else:
                self._scheduler._queue_task(self)

    def _wait_on_future(self, future):
        future.add_done_callback(lambda src: self._scheduler._queue_task(self, src))
        self._waits_on_future = future
        if self._cancel:
            # If we are supposed to cancel the coroutine but now we are waiting on a future
            # (because, remember, the cancellation can be caught and handled like any other
            # exception inside the coroutine), then we reset the cancel flag on us,
            # and instead pass it one level lower.
            # This continues recursively (technically we'd process it iteratively) until the
            # lowest-level future which will then be cancelled, produce a CancelledError
            # exception and that exception will bubble the stack up in the opposite direction.
            if future.cancel():
                self._cancel = False


def ensure_future(future_or_coroutine, scheduler):
    """
    Convert *future_or_coroutine* to a Future instance belonging to *scheduler*.

    If *future_or_coroutine* is not a coroutine, it is assumed to be a Future
    and consequently adopted to *scheduler*.
    """
    d = dir(future_or_coroutine)
    # The first case should be obvious
    # The second case is asynchronous generator objects, i.e.
    # async def foo(): yield 1; yield 2; ...
    # => foo() returns an asynchronous generator object
    # The third case is non-obvious but catches various coroutine-like objects,
    # including async_generator_asend-objects, which is, in essence, a single-step coroutine
    # corresponding to one yield of the generator.
    if inspect.iscoroutine(future_or_coroutine) or inspect.isasyncgen(future_or_coroutine) or ('close' in d and 'send' in d and 'throw' in d):
        return Task(future_or_coroutine, scheduler)
    future_or_coroutine._scheduler = scheduler
    return future_or_coroutine


@types.coroutine
def suspend():
    """
    Yield control to the scheduler for one iteration.
    """
    yield


def gather(*futures_or_coroutines, scheduler):
    """
    Wait for all futures and/or coroutines concurrently.

    The await-expression will return a list of results in arbitrary order.
    """
    def done(fut):
        futs.remove(fut)
        if gathering_future.done():
            fut.cancel()
            return
        elif fut.exception():
            gathering_future.set_exception(fut.exception())
        else:
            results.append(fut.result())
        if not futs:
            gathering_future.set_result(results)

    gathering_future = Future()
    futs = set()
    results = []
    for f in futures_or_coroutines:
        f = ensure_future(f, scheduler)
        futs.add(f)
        f.add_done_callback(done)
        scheduler.run(f)
    return gathering_future


async def as_completed(*futures_or_coroutines, scheduler):
    """
    Yields results as they become available.
    """
    def done(fut):
        futs.remove(fut)
        if fut.exception():
            blocker_future.set_exception(fut.exception())
            for f in futs:
                f.cancel()
        else:
            results.append(fut.result())
            if not blocker_future.done():
                blocker_future.set_result(None)

    blocker_future = Future()
    futs = set()
    results = []
    for f in futures_or_coroutines:
        f = ensure_future(f, scheduler)
        futs.add(f)
        f.add_done_callback(done)
        scheduler.run(f)

    while futs:
        await blocker_future
        blocker_future = Future()
        res = results
        results = []
        for r in res:
            yield r

    for r in results:
        yield r


class Scheduler:
    def __init__(self):
        self._queue = collections.deque()
        self._tasks = set()

    def tick(self):
        """
        Perform all currently pending actions, e.g. resuming runnable coroutines.
        """
        while self._queue:
            cb, args = self._queue.popleft()
            cb(*args)

    def run_until_complete(self, future_or_coroutine):
        """
        Run *future_or_coroutine* until completion.
        """
        future = ensure_future(future_or_coroutine, self)
        self._queue_task(future)
        while not future.done():
            self.tick()
        return future.result()

    def run_until_all_tasks_finished(self):
        """
        Run until there are no more running tasks/coroutines.
        """
        while self._tasks:
            self.tick()

    def run(self, future_or_coroutine):
        """
        Add *future_or_coroutine* to the running set of futures.
        """
        future = ensure_future(future_or_coroutine, self)
        if isinstance(future, Task):
            self._queue_task(future)
        return future

    def call_soon(self, cb, *args):
        """
        Call *cb* with *args* next time a .tick() happens.
        """
        self._queue.append((cb, args))

    def cancel_all_tasks(self):
        """
        Cancel all currently running tasks (running coroutines).
        """
        for task in self._tasks:
            task.cancel()

    def _queue_task(self, task_future, src=None):
        if task_future not in self._tasks:
            self._tasks.add(task_future)
            task_future.add_done_callback(lambda tf: self._tasks.remove(task_future))
        self._queue.append((task_future._tick, (src,)))
