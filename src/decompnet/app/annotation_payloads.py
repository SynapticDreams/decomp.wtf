"""Bounded metadata inspection shared by all research views."""
from ..rom.annotations import inspect, validate_annotation, validate_evidence


def parse(row, size):
    return (inspect(row['annotation'], validate_annotation, rom_size=size), inspect(row['evidence'], validate_evidence))


def raw(view):
    value = view.raw
    if value is None or isinstance(value, str) and len(value) <= 65536 and len(value.encode('utf-8', errors='replace')) <= 65536:
        return {'status': view.status, 'value': view.value, 'raw': value, 'truncated': False}
    return {'status': view.status, 'value': None, 'raw': value[:4096] if isinstance(value, str) else None, 'truncated': True}
