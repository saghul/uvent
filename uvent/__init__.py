# coding=utf8

# Copyright (C) 2012 Saúl Ibarra Corretgé <saghul@gmail.com>
#

__all__ = ['install']
__version__ = '0.2.0'


# Patchers

def patch_sleep():
    import gevent
    def sleep(seconds=0, ref=True):
        hub = gevent.hub.get_hub()
        loop = hub.loop
        watcher = loop.timer(max(seconds, 0), ref=ref)
        hub.wait(watcher)
    gevent.sleep = sleep
    gevent.hub.sleep = sleep


def patch_loop():
    from .loop import UVLoop
    from gevent.hub import Hub
    from gevent.resolver_thread import Resolver
    Hub.loop_class = UVLoop
    # The c-ares based resolver cannot be used for the moment
    Hub.resolver_class = Resolver


def install():
    patch_sleep()
    patch_loop()

