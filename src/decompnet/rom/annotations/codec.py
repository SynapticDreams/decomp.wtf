"""Bounded JSON inspection preserves unsupported original metadata without applying it."""
from dataclasses import dataclass
import json

MAX_BYTES = 65536
MAX_NODES = 4096
MAX_DEPTH = 16


def tree(value):
    stack, count = [(value, 0)], 0
    while stack:
        item, depth = stack.pop()
        count += 1
        if count > MAX_NODES or depth > MAX_DEPTH:
            raise ValueError('annotation JSON exceeds its node/depth budget')
        if isinstance(item, dict):
            if len(item) > MAX_NODES - count:
                raise ValueError('annotation JSON exceeds its node budget')
            if any(not isinstance(key, str) or len(key) > 128 for key in item):
                raise ValueError('annotation JSON keys must be bounded strings')
            stack.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            if len(item) > MAX_NODES - count:
                raise ValueError('annotation JSON exceeds its node budget')
            stack.extend((child, depth + 1) for child in item)
        elif isinstance(item, str):
            if len(item) > 4096 or '\0' in item:
                raise ValueError('annotation JSON string exceeds its budget')
        elif item is not None and type(item) not in (bool, int):
            raise ValueError('annotation JSON uses an unsupported value type')
        elif type(item) is int and not -(2**53 - 1) <= item <= 2**53 - 1:
            raise ValueError('annotation JSON integer exceeds its exact range')


def dump(value):
    tree(value)
    raw = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
    if len(raw.encode('utf-8')) > MAX_BYTES:
        raise ValueError('annotation JSON exceeds the 64 KiB budget')
    return raw


def _object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('annotation JSON has duplicate keys')
        value[key] = item
    return value


def load(raw):
    if not isinstance(raw, str) or len(raw) > MAX_BYTES or len(raw.encode('utf-8')) > MAX_BYTES:
        raise ValueError('annotation JSON is unavailable or exceeds its budget')
    value = json.loads(raw, object_pairs_hook=_object)
    tree(value)
    return value


@dataclass(frozen=True)
class View:
    status: str
    raw: object
    value: dict | None = None


def inspect(raw, validator, **context):
    if raw is None:
        return View('legacy_unknown', raw)
    try:
        value = load(raw)
        if not isinstance(value, dict) or type(value.get('version')) is not int:
            raise ValueError('annotation metadata needs an integer version')
        if value['version'] != 1:
            return View('unsupported_version', raw)
        validator(value, **context)
        return View('supported', raw, value)
    except (ValueError, TypeError, KeyError, RecursionError, OverflowError):
        return View('invalid', raw)
