====================
Implementation notes
====================

Even if libuv can be seen as a replacement of libev, there are subtle differences
that make the replacement niot as straightforward as it may initially seem. This is
not caused by the library itself but by the fact that gevent relies heavily in some
concepts ingrained in libev's design.


Reference counting
==================

In libev reference counting is implemented using a counter in the loop. If the loop
is referenced, the counter is incremented by one, and if it's unreferenced, the counter
is decremented. When the refcount reached zero, evn_run will return.

In libuv reference counting is done differently. It's not a counter it's a boolean like
property which handles have. If no handle if referencing the loop, uv_run will return.
Since it's not based on a counter, the actions are idempotent, that is, if you reference
a handle and then reference it again the action is not applied twice. Handles automatically
reference the loop when they are active, and this can be prevented by unreferencing them after
they are started.


Python reference counting
=========================

Since the gevent core is implemented in Python it can keep an object alive by calling
Py_INCREF, even if the object is not actually hold anywhere. In uvent this is emulated
by adding watchers to a set and removing them from there at the appropriate moments.


No priorities
=============

Unlike libev, there is no concept of *priority* for a handle in libuv, so this implementation
just ignores the value when passed along.


Penging handles
===============

libuv doesn't have a `ev_is_pending` equivalent. I never needed it, but since there is no way to
reliably return a proper value, False is returned always.


ev_feed_event
=============

NOTE: As of gevent 1.0rc1 this no longer applies. I'm keeping it for the record, but now a single
Prepare watcher is used which calls each registered callback in order.

Gevent implements a 'fake' type of watcher called a 'Callback watcher'. This wathcer is supposed
to call the given callback as soon as possible. Gevent implements this using a ev_prepare handle
which is actually never started, but manually fed.

uvent implements this type of watcher with a combination of a prepare and a check handle. They are
both started at the same time, and whichever kicks in first will stop both handles, thus guaranteeing
that the callback will only be called once. Since the loop may block for IO, in order to ensure that
this won't happen a global idle handle is started together with the prepare and check handles. When an
idle handle is active the loop with never block for IO.


Sleep behavior on value 0
=========================

The sleep function in gevent uses a timer (of course) but in case the given value is 0 an idle handle
is used. This leads to some cases in which gevent.sleep(0) doen't actually yield control to another
greenlet. In uvent sleep is patched to *always* use a timer, thus making the behavir consistent no
matter the value.

The problem with this behavior was acknowledged by the author of gevent and will probably be fixed
at some point. When that happens uvent will no longer need to patch the sleep function.


DNS
===

I initially tried to include a pycares based DNS resolver implementation with uvent, you may check the
git history and find the file there. However, due to all the black magic done by the Python socket module
for functions such as `gethostbyname` and `getaddrinfo` the implementation looked ugly and was actually
inefficient. Because of this uvent can only work with the threadpool based implementation.

A new standalone package will be released implementing a full DNS resolver using pycares, but without
doing all the crazy stuff the socket module does on its own.


Forking
=======

Things can go wrong if fork is used, it's advised no to do so. There is no ev_fork equivalent, but even if
there was, there are still threads that would need to be recreated, and probably other stuff.


Functions without an equivalent
===============================

Not all functionality in libev has a libuv counterpart. In cases where this happened NotImplementedError
is raised, but so far this has not been very relevant since the missing parts are not actually important
parts.


File objects
============

Gevent provides a module with a cooperative file implementation: gevent.fileobject. That module contains several
implementations, a thread based one and a i/o watcher based one. Uvent uses Poll handles as gevent io watchers, but
Poll handles don't support arbitrary file descriptors on Windows, it only supports sockets. So it's recommended that
FileObjectThread is used when using uvent.


Problem with Poll handles
=========================

Since the libev removal from libuv, only one Poll handle can be instantiated for a given fd. If more than one Poll handle
is created a segfault will occur. Since the gevent socket creates 2 'io' watchers (which use a Poll handle internally) some
kind of refcounting would be necessary to avoid creating more than one Poll handle for a given fd. Another solution would be
to implement our own socket module. **UPDATE:** This has been fixed with the inclusion of the SharedPoll pseudo-handle. 

