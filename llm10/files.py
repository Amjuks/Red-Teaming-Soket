"""Private atomic artifacts and reproducible identifiers."""
import hashlib
import json
import os
import tempfile
from pathlib import Path


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def publish_latest(root, directory):
    root, directory = Path(root), Path(directory)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    latest = root / 'latest'
    if latest.exists() and not latest.is_symlink():
        raise ValueError(f'Refusing to replace non-symlink: {latest}')
    temporary = root / f'.latest-{os.getpid()}'
    try:
        temporary.symlink_to(directory.name, target_is_directory=True)
        os.replace(temporary, latest)
    finally:
        if temporary.is_symlink(): temporary.unlink()
