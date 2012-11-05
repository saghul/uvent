# -*- coding: utf-8 -*-

from setuptools import setup
from uvent import __version__

setup(
    name             = 'uvent',
    version          = __version__,
    url              = 'https://github.com/saghul/uvent',
    author           = 'Saúl Ibarra Corretgé',
    author_email     = 'saghul@gmail.com',
    description      = 'A Gevent core implemented using libuv',
    long_description = open('README.rst', 'r').read(),
    #install_requires = ['pyuv>=0.9.1', 'gevent>=1.0'],
    packages         = ['uvent'],
    classifiers      = [
          "Development Status :: 3 - Alpha",
          "Intended Audience :: Developers",
          "License :: OSI Approved :: MIT License",
          "Programming Language :: Python",
          "Programming Language :: Python :: 2.6",
          "Programming Language :: Python :: 2.7",
          "Programming Language :: Python :: 3",
          "Programming Language :: Python :: 3.0",
          "Programming Language :: Python :: 3.1",
          "Programming Language :: Python :: 3.2"
    ]
)

