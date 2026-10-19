"""Bounded fingerprints of exported inputs and measured outputs; never follow private symlink targets."""
import hashlib
import json
import os
import stat

MAX_BYTES = 64 * 1024 * 1024
MAX_FILES = 16384


def read_regular(path, limit):
    """Read at most limit bytes without blocking on special files; reject changed evidence."""
    expected = path.lstat()
    if not stat.S_ISREG(expected.st_mode):
        raise ValueError('evidence_is_not_a_regular_file')
    descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(descriptor, 'rb') as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or (before.st_dev, before.st_ino) != (expected.st_dev, expected.st_ino):
            raise ValueError('evidence_is_not_a_regular_file')
        data = stream.read(limit)
        after = os.fstat(stream.fileno())
        if (before.st_size, before.st_mtime_ns, before.st_mode) != (after.st_size, after.st_mtime_ns, after.st_mode):
            raise ValueError('evidence_changed_during_read')
        return data, before


def fingerprint(root, *, outputs=False):
    digest, total, count = hashlib.sha256(), 0, 0
    try:
        if root.is_symlink() or not root.is_dir():
            return None
        stack = [(root, 0)]
        files = []
        while stack:
            directory, depth = stack.pop()
            if depth > 64:
                return None
            for entry in sorted(directory.iterdir()):
                if entry.name in ('.git', '__pycache__', 'build'):
                    continue
                info = entry.lstat()
                if stat.S_ISDIR(info.st_mode):
                    stack.append((entry, depth + 1))
                elif stat.S_ISREG(info.st_mode):
                    files.append(entry)
                else:
                    return None
                count += 1
                if count > MAX_FILES:
                    return None
        if outputs:
            if (root / 'build').is_symlink():
                return None
            files += [root / 'build' / name for name in ('verification.json', 'game.sms', 'game.gg')
                      if (root / 'build' / name).exists()]
        if len(files) > MAX_FILES:
            return None
        for path in sorted(files):
            before = path.lstat()
            if not stat.S_ISREG(before.st_mode):
                return None
            descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
            with os.fdopen(descriptor, 'rb') as stream:
                opened = os.fstat(stream.fileno())
                if not stat.S_ISREG(opened.st_mode) or (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
                    return None
                file_hash = hashlib.sha256()
                while data := stream.read(65536):
                    total += len(data)
                    if total > MAX_BYTES:
                        return None
                    file_hash.update(data)
                after = os.fstat(stream.fileno())
                if (before.st_size, before.st_mtime_ns, before.st_mode) != (after.st_size, after.st_mtime_ns, after.st_mode):
                    return None
            digest.update(json.dumps([path.relative_to(root).as_posix(), before.st_mode & 0o777,
                                      before.st_size, file_hash.hexdigest()], separators=(',', ':')).encode())
        return digest.hexdigest()
    except (OSError, UnicodeError, ValueError):
        return None
