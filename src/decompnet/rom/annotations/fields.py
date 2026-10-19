"""Shared strict fields for research schemas; booleans never stand in for integers."""
import re


def fields(value, names):
    if not isinstance(value, dict) or set(value) != set(names):
        raise ValueError('unsupported annotation fields')


def integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError('annotation integer is outside its allowed range')
    return value


def choice(value, choices):
    if not isinstance(value, str) or value not in choices:
        raise ValueError('unsupported annotation choice')
    return value


def sequence(value, low, high):
    if not isinstance(value, list) or not low <= len(value) <= high:
        raise ValueError('annotation list is empty or exceeds its budget')
    return value


def text(value, limit, *, identifier=False):
    if not isinstance(value, str) or not value.strip() or len(value) > limit or '\0' in value:
        raise ValueError('annotation text is empty or exceeds its budget')
    if identifier and not re.fullmatch('[A-Za-z_][A-Za-z0-9_]*', value):
        raise ValueError('annotation name must be an identifier')
    return value


def digest(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value):
        raise ValueError('annotation digest must be lowercase SHA256')
    return value


def version(value):
    if type(value) is not int or value != 1:
        raise ValueError('unsupported annotation version')
