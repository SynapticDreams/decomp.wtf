"""Digest-checked, bounded text responses shared by function and project archive subjects."""
import hashlib

from ..network import NetworkError
from . import banked_resplit_state as state


def read(options, item, origin, subject, filename, start, limit):
    entry = next((entry for entry in options if entry.key == item), None)
    if entry is None:
        raise NetworkError('saved item is unavailable for this archive subject')
    text = entry.body()
    if len(text.encode('utf-8')) > state.MAX_BYTES:
        raise NetworkError('saved text exceeds the recovery budget')
    if start > len(text):
        raise NetworkError('text start is outside the saved item')
    end = start + limit
    return {'origin': origin, **subject, 'item': entry.summary(), 'text': text[start:end],
            'start': start, 'characters': len(text), 'next_start': end if end < len(text) else None,
            'sha256': hashlib.sha256(text.encode('utf-8')).hexdigest(), 'chunk_characters': limit,
            'filename': f'{filename}_{entry.key.replace(":", "_")}.{entry.extension}'}
