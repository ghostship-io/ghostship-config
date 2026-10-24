"""Close inherited descriptors for Plex's ldconfig probe.

Plex's bundled Python 2.7 runs ``ctypes.util.find_library``, which starts
``/sbin/ldconfig -p`` through ``subprocess.Popen``. Python 2 does not close
inherited descriptors by default, so the interpreter's open packaged runtime
files reach the confined ``ghostship-plex//ldconfig`` domain, which logs a
``file_inherit`` denial at every probe.

This module wraps that one probe so the child closes every descriptor above
stderr before the exec. Nothing else in the interpreter changes.
"""
from __future__ import absolute_import

import subprocess


def _install():
    try:
        from ctypes import util
    except ImportError:
        return
    original = getattr(util, "find_library", None)
    if original is None or getattr(original, "_ghostship_close_fds", False):
        return

    def find_library(name):
        """find_library with descriptor inheritance closed for its helpers."""
        plain = subprocess.Popen

        class Closing(plain):
            def __init__(self, *args, **kwargs):
                # ``close_fds`` is the eighth positional argument; leave a
                # caller that states it alone.
                if len(args) < 8:
                    kwargs.setdefault("close_fds", True)
                plain.__init__(self, *args, **kwargs)

        subprocess.Popen = Closing
        try:
            return original(name)
        finally:
            subprocess.Popen = plain

    find_library._ghostship_close_fds = True
    util.find_library = find_library


_install()
