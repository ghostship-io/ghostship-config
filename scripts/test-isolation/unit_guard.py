"""Fail fast tests on host state or network access, even if a caller catches it."""
import argparse
import os
import re
import shutil
import socket
from pathlib import Path
import sys

_installed = False
_source = str(Path(__file__).resolve().parents[2])
_forbidden = ('/var/lib', '/run', '/srv/apps', '/etc/ghostship')
_network_commands = re.compile(r'^(curl|wget|ssh|scp|sftp|ghostship-notify|podman|docker(?:-compose)?|nix(?:-env|-instantiate)?|systemctl)$')


def protected(path, *, source_reads=False):
    if not isinstance(path, (str, bytes, os.PathLike)):
        return False
    path = os.fsdecode(path)
    if path.startswith('file:'):
        from urllib.parse import unquote, urlsplit
        path = unquote(urlsplit(path).path)
    absolute = os.path.abspath(path)
    # Self-hosted runners check out the repository below /run. Source reads
    # are fixtures, whereas unrelated runtime paths must remain forbidden.
    if source_reads and (absolute == _source or absolute.startswith(_source + '/')):
        return False
    if any(absolute == root or absolute.startswith(root + '/') for root in _forbidden):
        return True
    path = os.path.realpath(path)
    return any(path == root or path.startswith(root + '/') for root in _forbidden)


def at_directory(path, descriptor=None):
    if isinstance(path, (str, bytes, os.PathLike)) and descriptor is not None and descriptor >= 0:
        if not os.path.isabs(path):
            return os.path.join(os.readlink('/proc/self/fd/' + str(descriptor)), os.fsdecode(path))
    return path


def install():
    global _installed
    if _installed or not os.environ.get('GHOSTSHIP_UNIT_ROOT'):
        return
    _installed = True
    root = Path(os.environ['GHOSTSHIP_UNIT_ROOT'])
    log = Path(os.environ['GHOSTSHIP_UNIT_VIOLATIONS'])

    def deny(kind):
        with log.open('a') as stream:
            stream.write(kind + ': ' + os.environ.get('GHOSTSHIP_UNIT_CASE', 'child') + '\n')
        raise PermissionError('fast-test isolation: ' + kind)

    def audit(event, args):
        if event in {'open', 'os.listdir', 'os.scandir', 'os.mkdir', 'os.remove', 'os.rmdir',
                     'os.chmod', 'os.chown', 'os.truncate', 'os.utime', 'os.chdir'}:
            read = event in {'os.listdir', 'os.scandir'}
            if event == 'open':
                read = not (args[2] & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
            fd_index = {'os.remove': 1, 'os.rmdir': 1, 'os.mkdir': 2,
                        'os.chmod': 2, 'os.chown': 3, 'os.utime': 3}.get(event)
            path = at_directory(args[0], args[fd_index] if fd_index is not None else None)
            if protected(path, source_reads=read):
                deny('host state access')
        elif event in {'os.rename', 'os.link', 'os.symlink'}:
            paths = (at_directory(args[1], args[2]),) if event == 'os.symlink' else (
                at_directory(args[0], args[2]), at_directory(args[1], args[3]))
            if any(protected(path) for path in paths):
                deny('host state mutation')
        elif event in {'socket.connect', 'socket.bind', 'socket.getaddrinfo', 'socket.sendto',
                       'socket.sendmsg', 'urllib.Request'}:
            deny('network access')
        elif event in {'os.system', 'os.exec'}:
            deny('unguarded process execution')
        elif event == 'subprocess.Popen':
            executable = os.path.basename(os.fsdecode(args[0]))
            resolved = shutil.which(os.fsdecode(args[0])) or os.fsdecode(args[0])
            fixture = os.path.realpath(resolved).startswith(str(root) + os.sep)
            if _network_commands.fullmatch(executable) and not fixture:
                deny('external network or service command')
            command = args[1]
            if isinstance(command, (list, tuple)) and executable.startswith('python') and any(
                    option in command for option in ('-I', '-E', '-S')):
                deny('unguarded Python subprocess')
            child_env = args[3]
            if child_env is not None:
                # Explicit subprocess environments must retain the child guard.
                child_env['PYTHONDONTWRITEBYTECODE'] = '1'
                child_env.update({key: os.environ[key] for key in (
                    'GHOSTSHIP_UNIT_ROOT', 'GHOSTSHIP_UNIT_VIOLATIONS', 'PYTHONPATH')
                    if key not in child_env})
                guard = str(Path(__file__).parent)
                if guard not in child_env['PYTHONPATH'].split(os.pathsep):
                    child_env['PYTHONPATH'] = guard + os.pathsep + child_env['PYTHONPATH']
        elif event.startswith('sqlite3.connect') and args and protected(args[0]):
            deny('host database access')

    sys.addaudithook(audit)
    # urllib3 otherwise binds an IPv6 probe socket while being imported.
    socket.has_ipv6 = False
    # Metadata probes are not audit events, but must not inspect live state.
    for name in ('stat', 'lstat', 'access'):
        original = getattr(os, name)
        def guarded(path, *args, _original=original, **kwargs):
            if isinstance(path, (str, bytes, os.PathLike)):
                path = at_directory(path, kwargs.get('dir_fd'))
                absolute = os.path.abspath(os.fsdecode(path))
                source = (absolute == _source or absolute.startswith(_source + '/')
                          or _source.startswith(absolute.rstrip('/') + '/'))
                if not source and any(absolute == base or absolute.startswith(base + '/') for base in _forbidden):
                    deny('host state metadata')
            return _original(path, *args, **kwargs)
        setattr(os, name, guarded)
    # Test-only defaults follow newly added runtime file options automatically.
    # Explicit paths are never rewritten: a bad fixture still trips the guard.
    parse_args = argparse.ArgumentParser.parse_args
    def isolated_args(parser, *args, **kwargs):
        for action in parser._actions:
            if isinstance(action.default, str) and protected(action.default):
                action.default = str(root / 'defaults' / action.default.lstrip('/'))
        return parse_args(parser, *args, **kwargs)
    argparse.ArgumentParser.parse_args = isolated_args
