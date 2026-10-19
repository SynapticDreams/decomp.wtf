"""Versioned research data. Validation establishes shape and bounds, never truth or live mapping."""
from .codec import inspect as inspect, dump as dump
from .payloads import validate as validate_annotation
from .evidence import validate as validate_evidence

__all__ = ['inspect', 'dump', 'validate_annotation', 'validate_evidence']
