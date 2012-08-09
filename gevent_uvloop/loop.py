# coding=utf8

# Copyright (C) 2011 Saúl Ibarra Corretgé <saghul@gmail.com>
#

__all__ = ['UVLoop', 'sleep']

import functools
import pyuv
import signal
import sys


class UVLoop(object):
    MINPRI = -2
    MAXPRI = 2

    def __init__(self, flags=None, default=True):
        if default:
            self._loop = pyuv.Loop.default_loop()
        else:
            self._loop = pyuv.Loop()
        self._signal_checker = pyuv.Signal(self._loop)
        self._ticker = Ticker(self)
        self._handles = set()
        try:
            signal.signal(signal.SIGINT, self._handle_sigint)
        except ValueError:
            # TODO: signal handlers cannot be added from a thread other than Main
            pass

    def destroy(self):
        self._handles.clear()
        self._ticker = None
        self._signal_checker = None
        self._loop = None

    def _handle_sigint(self, signum, frame):
        self.handle_error(None, SystemExit, 1, None)

    def _handle_syserr(self, message, errno):
        self.handle_error(None, SystemError, SystemError(message + ': ' + os.strerror(errno)), None)

    def handle_error(self, context, type, value, tb):
        error_handler = self.error_handler
        if error_handler is not None:
            # we do want to do getattr every time so that setting Hub.handle_error property just works
            handle_error = getattr(error_handler, 'handle_error', error_handler)
            handle_error(context, type, value, tb)
        else:
            self._default_handle_error(context, type, value, tb)

    def _default_handle_error(self, context, type, value, tb):
        import traceback
        traceback.print_exception(type, value, tb)
        # TODO: stop loop

    def run(self, nowait=False, once=False):
        if nowait:
            raise RuntimeError('nowait is not supported')
        self._signal_checker.start()
        self._signal_checker.unref()
        if once:
            self._loop.run_once()
        else:
            self._loop.run()

    def reinit(self):
        raise NotImplementedError

    def ref(self):
        raise NotImplementedError

    def unref(self):
        raise NotImplementedError

    def break_(self, how):
        raise NotImplementedError

    def verify(self):
        pass

    def now(self):
        return self._loop.now()

    def update(self):
        self._loop.update_time()

    @property
    def default(self):
        return self._loop.default

    @property
    def iteration(self):
        raise NotImplementedError

    @property
    def depth(self):
        raise NotImplementedError

    @property
    def backend(self):
        raise NotImplementedError

    @property
    def backend_int(self):
        raise NotImplementedError

    @property
    def pendingcnt(self):
        raise NotImplementedError

    @property
    def activecnt(self):
        return self._loop.active_handles

    @property
    def origflags(self):
        raise NotImplementedError

    @property
    def origflags_int(self):
        raise NotImplementedError

    def io(self, fd, events, ref=True, priority=None):
        return Io(self, fd, events, ref)

    def timer(self, after, repeat=0.0, ref=True, priority=None):
        return Timer(self, after, repeat, ref)

    def prepare(self, ref=True, priority=None):
        return Prepare(self, ref)

    def idle(self, ref=True, priority=None):
        return Idle(self, ref)

    def check(self, ref=True, priority=None):
        return Check(self, ref)

    def async(self, ref=True, priority=None):
        return Async(self, ref)

    def stat(self, path, interval=0.0, ref=True, priority=None):
        raise NotImplementedError

    def fork(self, ref=True, priority=None):
        return NoOp(self, ref)

    def child(self, pid, trace=0, ref=True):
        raise NotImplementedError

    def install_sigchld(self):
        raise NotImplementedError

    def signal(self, signum, ref=True, priority=None):
        raise NotImplementedError

    def callback(self, priority=None):
        return Callback(self)

    def run_callback(self, func, *args, **kw):
        result = Callback(self)
        result.start(func, *args)
        return result

    def fileno(self):
        raise NotImplementedError


class Ticker(object):

    def __init__(self, loop):
        self._handle = pyuv.Idle(loop._loop)

    def _cb(self, handle):
        self._handle.stop()

    def tick(self):
        if not self._handle.active:
            self._handle.start(self._cb)
            self._handle.unref()


class Watcher(object):

    @property
    def callback(self):
        return self._callback

    @property
    def active(self):
        return self._handle and self._handle.active

    @property
    def pending(self):
        return False

    def _get_ref(self):
        return self._ref
    def _set_ref(self, value):
        self._ref = value
        if self._handle:
            op = self._handle._ref if value else self._handle.unref
            op()
    ref = property(_get_ref, _set_ref)
    del _get_ref, _set_ref

    def start(self, callback, *args):
        self.loop._handles.add(self)
        self._callback = functools.partial(callback, *args)

    def stop(self):
        self.loop._handles.discard(self)
        self._callback = None

    def feed(self, revents, callback, *args):
        raise NotImplementedError

    def _run_callback(self):
        if self._callback:
            try:
                self._callback()
            except:
                self.loop.handle_error(self, *sys.exc_info())
            finally:
                if not self.active:
                    self.stop()


class NoOp(Watcher):

    def __init__(self, loop, ref=True):
        self._ref = ref
        self._callback = None
        self._handle = None

    def start(self, *args, **kw):
        pass

    def stop(self):
        pass


class Callback(Watcher):

    def __init__(self, loop, ref=True):
        self.loop = loop
        self._ref = ref
        self._callback = None
        self._handle = pyuv.Prepare(self.loop._loop)

    def _cb(self, handle):
        try:
            self._callback()
        except:
            self.loop.handle_error(self, *sys.exc_info())
        finally:
            self.stop()

    def start(self, callback, *args):
        super(Callback, self).start(callback, *args)
        self.loop._ticker.tick()
        self._handle.start(self._cb)
        if not self._ref:
            self._handle.unref()

    def stop(self):
        self._handle.stop()
        super(Callback, self).stop()


class Timer(Watcher):

    def __init__(self, loop, after=0.0, repeat=0.0, ref=True):
        if repeat < 0.0:
            raise ValueError("repeat must be positive or zero: %r" % repeat)
        self.loop = loop
        self._after = after
        self._repeat = repeat
        self._ref = ref
        self._callback = None
        self._handle = pyuv.Timer(self.loop._loop)

    def _timer_cb(self, handle):
        self._run_callback()

    def start(self, callback, *args, **kw):
        super(Timer, self).start(callback, *args)
        if kw.get('update', True):
            self.loop.update()
        self._handle.start(self._timer_cb, self._after, self._repeat)
        if not self._ref:
            self._handle.unref()

    def stop(self):
        self._handle.stop()
        super(Timer, self).stop()

    def again(self, callback, *args, **kw):
        if not self._handle:
            raise RuntimeError('timer not started')
        self.loop._handles.add(self)
        self._callback = functools.partial(callback, *args)
        if kw.get('update', True):
            self.loop.update()
        self._handle.again()

    @property
    def at(self):
        raise NotImplementedError


class Prepare(Watcher):

    def __init__(self, loop, ref=True):
        self.loop = loop
        self._ref = ref
        self._callback = None
        self._handle = pyuv.Prepare(self.loop._loop)

    def _prepare_cb(self, handle):
        self._run_callback()

    def start(self, callback, *args):
        super(Prepare, self).start(callback, *args)
        self._handle.start(self._prepare_cb)
        if not self._ref:
            self._handle.unref()

    def stop(self):
        self._handle.stop()
        super(Prepare, self).stop()


class Idle(Watcher):

    def __init__(self, loop, ref=True):
        self.loop = loop
        self._ref = ref
        self._callback = None
        self._handle = pyuv.Idle(self.loop._loop)

    def _idle_cb(self, handle):
        self._run_callback()

    def start(self, callback, *args):
        super(Idle, self).start(callback, *args)
        self._handle.start(self._idle_cb)
        if not self._ref:
            self._handle.unref()

    def stop(self):
        self._handle.stop()
        super(Idle, self).stop()


class Check(Watcher):

    def __init__(self, loop, ref=True):
        self.loop = loop
        self._ref = ref
        self._callback = None
        self._handle = pyuv.Check(self.loop._loop)

    def _check_cb(self, handle):
        self._run_callback()

    def start(self, callback, *args):
        super(Check, self).start(callback, *args)
        self._handle.start(self._check_cb)
        if not self._ref:
            self._handle.unref()

    def stop(self):
        self._handle.stop()
        super(Check, self).stop()


class Io(Watcher):

    def __init__(self, loop, fd, events, ref=True):
        self.loop = loop
        self._ref = ref
        self._fd = fd
        self._events = self._ev2uv(events)
        self._callback = None
        self._handle = pyuv.Poll(self.loop._loop, self._fd)

    @classmethod
    def _ev2uv(cls, events):
        uv_events = 0
        if events & 1:
            uv_events |= pyuv.UV_READABLE
        if events & 2:
            uv_events |= pyuv.UV_WRITABLE
        return uv_events

    def _poll_cb(self, handle, events, error):
        if error is not None:
            self._handle.stop()
            return
        try:
            self._callback()
        except:
            self.loop.handle_error(self, *sys.exc_info())
            self.stop()
        finally:
            if not self.active:
                self.stop()

    def start(self, callback, *args, **kw):
        super(Io, self).start(callback, *args)
        self._handle.start(self._events, self._poll_cb)
        if not self._ref:
            self._handle.unref()

    def stop(self):
        self._handle.stop()
        super(Io, self).stop()

    def _get_fd(self):
        return self._fd
    def _set_fd(self, value):
        self._fd = value
        self._handle.stop()
        self._handle = pyuv.Poll(self.loop._loop, self._fd)
    fd = property(_get_fd, _set_fd)
    del _get_fd, _set_fd

    def _get_events(self):
        return self._events
    def _set_events(self, value):
        self._events = self._ev2uv(value)
        self._handle.start(self._events, self._poll_cb)
    events = property(_get_events, _set_events)
    del _get_events, _set_events

    @property
    def events_str(self):
        r = []
        if self._events & pyuv.UV_READABLE:
            r.append('UV_READABLE')
        if self._events & pyuv.UV_WRITABLE:
            r.append('UV_WRITABLE')
        return '|'.join(r)


class Async(Watcher):

    def __init__(self, loop, ref=True):
        self.loop = loop
        self._ref = ref
        self._callback = None
        self._handle = pyuv.Async(self.loop._loop, self._async_cb)

    def _async_cb(self, handle):
        self._run_callback()

    def start(self, callback, *args, **kw):
        super(Async, self).start(callback, *args)
        if not self._ref:
            self._handle.unref()

    def stop(self):
        super(Async, self).stop()

    def send(self):
        self._handle.send()

