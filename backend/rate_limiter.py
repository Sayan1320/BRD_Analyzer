"""
Shared rate limiter instance used by main.py and requirement_summarizer_app.py.
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address, storage_uri="memory://")
