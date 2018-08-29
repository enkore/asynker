import pytest

from asynker import Scheduler, suspend, Future, CancelledError, gather, as_completed


def test_chain():
    flag = False

    async def other():
        nonlocal flag
        await suspend()
        flag = True
        return 42

    async def entry():
        return await other()

    sched = Scheduler()
    assert sched.run_until_complete(entry()) == 42
    assert flag


def test_chain_exc():
    async def other():
        raise KeyError('Foo')

    async def entry():
        return await other()

    sched = Scheduler()
    with pytest.raises(KeyError):
        sched.run_until_complete(entry())


def test_loop():
    f = Future()

    def get_response():
        return f

    async def entry():
        return await get_response()

    sched = Scheduler()
    entry_future = sched.run(entry())

    sched.tick()
    assert not entry_future.done()
    f.set_result(666)
    assert not entry_future.done()
    sched.tick()
    assert entry_future.done()
    assert entry_future.result() == 666


def test_loop_exc():
    f = Future()

    def get_response():
        return f

    async def entry():
        return await get_response()

    sched = Scheduler()
    entry_future = sched.run(entry())

    print(entry_future.done())
    sched.tick()
    assert not entry_future.done()
    f.set_exception(KeyError)
    assert not entry_future.done()
    sched.tick()
    assert entry_future.done()
    with pytest.raises(KeyError):
        entry_future.result()


def test_cancel():
    async def entry():
        await suspend()
        assert False

    sched = Scheduler()
    future = sched.run(entry())
    assert future.cancel()
    assert not future.cancelled()
    sched.tick()
    assert future.cancelled()
    with pytest.raises(CancelledError):
        future.result()


def test_cancel_self():
    async def entry():
        future.cancel()
        await suspend()
        assert False

    sched = Scheduler()
    future = sched.run(entry())
    sched.tick()
    assert future.cancelled()
    with pytest.raises(CancelledError):
        future.result()


def test_cancel_self_late():
    async def entry():
        await suspend()
        future.cancel()

    sched = Scheduler()
    future = sched.run(entry())
    sched.tick()
    assert future.cancelled()
    with pytest.raises(CancelledError):
        future.result()


def test_cancel_all_tasks():
    async def entry():
        await suspend()
        assert False

    sched = Scheduler()
    sched.run(entry())
    sched.run(entry())
    sched.run(entry())
    sched.cancel_all_tasks()
    sched.tick()


def test_run_until_all_tasks_finished():
    async def entry():
        await suspend()
        return 1234

    sched = Scheduler()
    future = sched.run(entry())
    sched.run_until_all_tasks_finished()
    assert future.result() == 1234


def test_gather():
    fut1 = Future()
    fut2 = Future()
    fut3 = Future()
    sched = Scheduler()
    gf = gather(fut1, fut2, fut3, scheduler=sched)
    assert not gf.done()
    fut1.set_result(1)
    assert not gf.done()
    fut3.set_result(3)
    fut2.set_result(2)
    assert not gf.done()
    sched.tick()
    assert gf.done()
    assert gf.result() == [1, 3, 2]


def test_gather_exc():
    fut1 = Future()
    fut2 = Future()
    fut3 = Future()
    sched = Scheduler()
    gf = gather(fut1, fut2, fut3, scheduler=sched)
    assert not gf.done()
    fut1.set_result(1)
    assert not gf.done()
    fut3.set_exception(KeyError)
    assert not gf.done()
    sched.tick()
    assert gf.done()
    with pytest.raises(KeyError):
        gf.result()


def test_as_completed():
    fut1 = Future()
    fut2 = Future()
    fut3 = Future()
    sched = Scheduler()
    ac = as_completed(fut1, fut2, fut3, scheduler=sched)

    fut1.set_result(5)
    assert sched.run_until_complete(ac.__anext__()) == 5
    fut2.set_result(1)
    assert sched.run_until_complete(ac.__anext__()) == 1
    fut3.set_result(3)
    assert sched.run_until_complete(ac.__anext__()) == 3
