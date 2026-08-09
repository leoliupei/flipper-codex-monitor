import ctypes
import re
import sys
import unicodedata
from functools import lru_cache
from typing import Optional, Tuple


LABEL_MAX = 7
_UTF8_ENCODING = 0x08000100


@lru_cache(maxsize=1)
def _core_foundation() -> Optional[Tuple[ctypes.CDLL, ctypes.c_void_p, ctypes.c_void_p]]:
    if sys.platform != "darwin":
        return None
    try:
        framework = ctypes.CDLL(
            "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
        )
        framework.CFStringCreateWithCString.argtypes = [
            ctypes.c_void_p,
            ctypes.c_char_p,
            ctypes.c_uint32,
        ]
        framework.CFStringCreateWithCString.restype = ctypes.c_void_p
        framework.CFStringCreateMutableCopy.argtypes = [
            ctypes.c_void_p,
            ctypes.c_long,
            ctypes.c_void_p,
        ]
        framework.CFStringCreateMutableCopy.restype = ctypes.c_void_p
        framework.CFStringTransform.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_bool,
        ]
        framework.CFStringTransform.restype = ctypes.c_bool
        framework.CFStringGetLength.argtypes = [ctypes.c_void_p]
        framework.CFStringGetLength.restype = ctypes.c_long
        framework.CFStringGetMaximumSizeForEncoding.argtypes = [
            ctypes.c_long,
            ctypes.c_uint32,
        ]
        framework.CFStringGetMaximumSizeForEncoding.restype = ctypes.c_long
        framework.CFStringGetCString.argtypes = [
            ctypes.c_void_p,
            ctypes.c_char_p,
            ctypes.c_long,
            ctypes.c_uint32,
        ]
        framework.CFStringGetCString.restype = ctypes.c_bool
        framework.CFRelease.argtypes = [ctypes.c_void_p]
        to_latin = ctypes.c_void_p.in_dll(
            framework, "kCFStringTransformToLatin"
        )
        strip_marks = ctypes.c_void_p.in_dll(
            framework, "kCFStringTransformStripCombiningMarks"
        )
        return framework, to_latin, strip_marks
    except (AttributeError, OSError, ValueError):
        return None


def _to_latin(value: str) -> Optional[str]:
    loaded = _core_foundation()
    if loaded is None:
        return None
    framework, to_latin, strip_marks = loaded
    source = framework.CFStringCreateWithCString(
        None, value.encode("utf-8"), _UTF8_ENCODING
    )
    if not source:
        return None
    mutable = None
    try:
        mutable = framework.CFStringCreateMutableCopy(None, 0, source)
        if not mutable:
            return None
        if not framework.CFStringTransform(mutable, None, to_latin, False):
            return None
        framework.CFStringTransform(mutable, None, strip_marks, False)
        length = framework.CFStringGetLength(mutable)
        size = framework.CFStringGetMaximumSizeForEncoding(
            length, _UTF8_ENCODING
        ) + 1
        if size <= 1:
            return None
        buffer = ctypes.create_string_buffer(size)
        if not framework.CFStringGetCString(
            mutable, buffer, size, _UTF8_ENCODING
        ):
            return None
        return buffer.value.decode("utf-8")
    finally:
        if mutable:
            framework.CFRelease(mutable)
        framework.CFRelease(source)


def thread_label(value: object) -> str:
    """Create the Flipper label from the thread title only."""
    if not isinstance(value, str) or not value.strip():
        return "NO_NAME"

    has_non_ascii = any(ord(character) > 127 for character in value)
    if has_non_ascii:
        latin = _to_latin(value)
        if latin:
            words = re.findall(r"[A-Za-z]+|[0-9]+", latin)
            pieces = []
            for word in words:
                if word.isupper() and len(word) <= 4:
                    pieces.append(word)
                else:
                    pieces.append(word[0])
            initials = "".join(pieces).upper()
            if initials:
                return initials[:LABEL_MAX]

    normalized = unicodedata.normalize("NFKD", value)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    label = re.sub(r"[^A-Za-z0-9]+", "_", ascii_text).strip("_").upper()
    return label[:LABEL_MAX] or "NO_NAME"
