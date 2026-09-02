"""Traditional → Simplified conversion, in one place.

tw2sp (not t2s): it handles 著→着 correctly and maps Taiwan vocabulary to
mainland usage (資訊→信息), which is the owner's rule for Chinese sources.
OpenCC converts characters and phrases but not punctuation, so the corner
brackets are mapped here.

Fail-open by design: when OpenCC is unavailable the caller gets an identity
function plus a reason, and the text survives unconverted rather than the
run dying.
"""

_PUNCT_MAP = str.maketrans({"「": "“", "」": "”", "『": "‘", "』": "’"})


def simplifier() -> tuple[callable, str]:
    """Return (convert, error). `error` is empty when conversion is live."""
    try:
        from opencc import OpenCC

        cc = OpenCC("tw2sp")
        return (lambda text: cc.convert(text).translate(_PUNCT_MAP)), ""
    except Exception as exc:  # noqa: BLE001 — degrade, never abort a run
        return (lambda text: text), f"conversion unavailable ({exc}); keeping original script"
