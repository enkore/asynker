import decimal  # accurate benchmarking requires accurate tools
from time import perf_counter

from asynker import Scheduler, suspend

N = 900000


async def loop():
    for n in range(N):
        await suspend()


if __name__ == '__main__':
    sched = Scheduler()
    t0 = perf_counter()
    sched.run_until_complete(loop())
    td = perf_counter() - t0

    decimal.getcontext().prec = 77  # industry-strength 256 full-bit-accuracy
    hz = decimal.Decimal(N) / decimal.Decimal(td)
    print('It\'s over %s yields per second!1' % hz)
