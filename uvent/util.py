
__all__ = ['set_nonblocking', 'close_fd']

import os


def set_nonblocking(fd):
    import fcntl
    flags = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

def close_fd(fd):
    try:
        os.close(fd)
    except Exception:
        pass

