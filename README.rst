Asynker: Coroutine scheduler for the "await" syntax
===================================================

Asynker (IPA: /eɪˈsɪŋkɜːn/) is pretty much the least amount of code you need
to use the "await" syntax. Typically packages like asyncio or curio implement
two concepts at once: a scheduler and an event loop. The scheduler is a piece
of code that decides what to run next and then runs it. The event loop is
a piece of code that tells the scheduler what it *can* run.

Asynker only provides the scheduling part. This generally only makes sense if
you are using something else as the event loop, e.g. something callback-based.
Asynker allows you to use a callback-based system and easily convert it into
a coroutine/await-based system.

The Future class used in Asynker is unrelated to any of the various Future
classes found in the Python standard library (for now, anyway).

Features
--------

- Does over 900000 yields per second :sup:`[citation needed]`
- The API is like asyncio but different enough to probably introduce interesting behaviours
  for study in your code
- If all you wanted was to use "await" in your code without loading 500 kB of code,
  then this is for you

.. The name is a pun on asyncore and async+kern(el),
   kernel being the set of vectors mapped to zero in linear algebra.
   Also... asynker... as in... it makes things asynk.
