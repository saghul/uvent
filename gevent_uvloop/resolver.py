# coding=utf8

# Copyright (C) 2012 Saúl Ibarra Corretgé <saghul@gmail.com>
#

__all__ = ['Resolver']

import pycares
import pyuv
import socket

from collections import namedtuple
from functools import partial
from gevent.hub import get_hub, Waiter


Result = namedtuple('Result', ['value', 'exception'])

class Resolver(object):

    _ares_flag_map = [(getattr(socket, 'NI_NUMERICHOST', 1), pycares.ARES_NI_NUMERICHOST),
                      (getattr(socket, 'NI_NUMERICSERV', 2), pycares.ARES_NI_NUMERICSERV),
                      (getattr(socket, 'NI_NOFQDN',      4), pycares.ARES_NI_NOFQDN),
                      (getattr(socket, 'NI_NAMEREQD',    8), pycares.ARES_NI_NAMEREQD),
                      (getattr(socket, 'NI_DGRAM',      16), pycares.ARES_NI_DGRAM)]

    _ares_errno_map = {pycares.errno.ARES_ENOTFOUND: (socket.gaierror, (8, 'nodename nor servname provided, or not known')),
                       pycares.errno.ARES_ENODATA: (socket.gaierror, (8, 'nodename nor servname provided, or not known'))}
    _ares_errno_map2 = {pycares.errno.ARES_ENOTFOUND: (socket.herror, (1, 'Unknown host')),
                        pycares.errno.ARES_ENODATA: (socket.gaierror, (8, 'nodename nor servname provided, or not known'))}
    _addrinfo_errno_map = {pyuv.errno.UV_ENOENT: (socket.gaierror, (8, 'nodename nor servname provided, or not known'))}

    def __init__(self, hub=None):
        self.hub = hub or get_hub()
        self._channel = pycares.Channel(sock_state_cb=self._sock_state_cb)
        self._timer = pyuv.Timer(self.hub.loop._loop)
        self._fd_map = {}

    def _sock_state_cb(self, fd, readable, writable):
        if readable or writable:
            if fd not in self._fd_map:
                # New socket
                handle = pyuv.Poll(self.hub.loop._loop, fd)
                handle.fd = fd
                self._fd_map[fd] = handle
            else:
                handle = self._fd_map[fd]
            if not self._timer.active:
                self._timer.start(self._timer_cb, 1, 1)
            handle.start(pyuv.UV_READABLE if readable else 0 | pyuv.UV_WRITABLE if writable else 0, self._poll_cb)
        else:
            # Socket is now closed
            handle = self._fd_map.pop(fd)
            handle.close()
            if not self._fd_map:
                self._timer.stop()

    def _timer_cb(self, timer):
        self._channel.process_fd(pycares.ARES_SOCKET_BAD, pycares.ARES_SOCKET_BAD)

    def _poll_cb(self, handle, events, error):
        read_fd = handle.fd
        write_fd = handle.fd
        if error is not None:
            # There was an error, pretend the socket is ready
            self._channel.process_fd(read_fd, write_fd)
            return
        if not events & pyuv.UV_READABLE:
            read_fd = pycares.ARES_SOCKET_BAD
        if not events & pyuv.UV_WRITABLE:
            write_fd = pycares.ARES_SOCKET_BAD
        self._channel.process_fd(read_fd, write_fd)

    def close(self):
        self._channel.destroy()
        for handle in self._fd_map.itervalues():
            handle.stop()
        self._fd_map.clear()
        self._timer = None
        self.hub = None

    def _ares_cb(self, cb, result, error):
        if error is not None:
            error_data = self._ares_errno_map.get(error)
            if not error_data:
                exc = socket.gaierror(error, pycares.errno.strerror(error))
            else:
                klass, args = error_data
                exc = klass(*args)
            cb(Result(None, exc))
        else:
            cb(Result(result, None))

    def _ares_cb2(self, cb, result, error):
        if error is not None:
            error_data = self._ares_errno_map2.get(error)
            if not error_data:
                exc = socket.gaierror(error, pycares.errno.strerror(error))
            else:
                klass, args = error_data
                exc = klass(*args)
            cb(Result(None, exc))
        else:
            cb(Result(result, None))

    def _addrinfo_cb(self, cb, result, error):
        if error is not None:
            error_data = self._addrinfo_errno_map.get(error)
            if not error_data:
                exc = socket.gaierror(error, pycares.errno.strerror(error))
            else:
                klass, args = error_data
                exc = klass(*args)
            cb(Result(None, exc))
        else:
            cb(Result(result, None))

    def gethostbyname(self, hostname):
        waiter = Waiter(self.hub)
        cb = partial(self._ares_cb, waiter)
        self._channel.gethostbyname(hostname, socket.AF_INET, cb)
        result = waiter.get()
        if not result.addresses:
            raise socket.gaierror(8, 'nodename nor servname provided, or not known')
        return result.addresses[0]

    def gethostbyname_ex(self, hostname):
        waiter = Waiter(self.hub)
        cb = partial(self._ares_cb, waiter)
        self._channel.gethostbyname(hostname, socket.AF_INET, cb)
        result = waiter.get()
        if not result.addresses:
            raise socket.gaierror(8, 'nodename nor servname provided, or not known')
        return (result.name, result.aliases, result.addresses)

    def gethostbyaddr(self, ip_address):
        waiter = Waiter(self.hub)
        cb = partial(self._ares_cb2, waiter)
        try:
            self._channel.gethostbyaddr(ip_address, cb)
        except ValueError:
            result = self.getaddrinfo(ip_address, None, family=socket.AF_UNSPEC, socktype=socket.SOCK_DGRAM)
            ip_address = result[0][-1][0]
            self._channel.gethostbyaddr(ip_address, cb)
        result = waiter.get()
        aliases = result.aliases if result.name == 'localhost' else [pycares.reverse_address(ip_address)]
        return (result.name, aliases, result.addresses)

    def getnameinfo(self, sockaddr, flags):
        if not isinstance(flags, int):
            raise TypeError('an integer is required')
        if not isinstance(sockaddr, tuple):
            raise TypeError('getnameinfo() argument 1 must be a tuple')
        try:
            port = int(sockaddr[1])
        except Exception:
            raise TypeError('an integer is required')
        _flags = pycares.ARES_NI_LOOKUPHOST|pycares.ARES_NI_LOOKUPSERVICE
        for socket_flag, ares_flag in self._ares_flag_map:
            if socket_flag & flags:
                _flags |= ares_flag
        try:
            result = self.getaddrinfo(sockaddr[0], sockaddr[1], family=socket.AF_UNSPEC, socktype=socket.SOCK_DGRAM)
        except ValueError:
            raise socket.gaierror(8, 'nodename nor servname provided, or not known')
        if len(result) != 1:
            raise socket.error('sockaddr resolved to multiple addresses')
        family, socktype, proto, name, address = result[0]
        if family == socket.AF_INET:
            if len(sockaddr) != 2:
                raise socket.error("IPv4 sockaddr must be 2 tuple")
        elif family == socket.AF_INET6:
            address = address[:2] # TODO: is this ok?
        waiter = Waiter(self.hub)
        cb = partial(self._ares_cb, waiter)
        self._channel.getnameinfo(address, _flags, cb)
        result = waiter.get()
        return (result.node, result.service or '0')

    def getaddrinfo(self, host, port, family=0, socktype=0, proto=0, flags=0):
        if port is None:
            port = 0
        try:
            port = int(port)
        except ValueError:
            try:
                port = socket.getservbyname(port)
            except socket.error:
                raise socket.gaierror(8, 'nodename nor servname provided, or not known')
        if family not in (socket.AF_UNSPEC, socket.AF_INET, socket.AF_INET6):
            raise socket.gaierror(5, 'ai_family not supported')
        waiter = Waiter(self.hub)
        cb = partial(self._addrinfo_cb, waiter)
        pyuv.util.getaddrinfo(self.hub.loop._loop, host, cb, port, family, socktype, proto, flags)
        result = waiter.get()
        return [tuple(x) for x in result]

