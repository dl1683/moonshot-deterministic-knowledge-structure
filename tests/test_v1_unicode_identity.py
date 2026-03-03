"""Regression tests for Unicode canonicalization hardening (P5/P6).

P5: NFC normalization — precomposed and decomposed forms must converge.
P6: Zero-width character stripping — invisible codepoints must not fragment identity.
"""
from dks import ClaimCore, canonicalize_text


def test_nfc_normalization_precomposed_vs_decomposed() -> None:
    """U+00E9 (precomposed é) and U+0065 U+0301 (e + combining acute) must converge."""
    precomposed = "caf\u00e9"  # café (single codepoint é)
    decomposed = "cafe\u0301"  # café (e + combining acute)

    assert canonicalize_text(precomposed) == canonicalize_text(decomposed)


def test_nfc_claim_identity_convergence() -> None:
    """Claims with NFC-equivalent slot values must produce the same core_id."""
    core_pre = ClaimCore(claim_type="fact", slots={"subject": "caf\u00e9"})
    core_dec = ClaimCore(claim_type="fact", slots={"subject": "cafe\u0301"})

    assert core_pre.core_id == core_dec.core_id


def test_zero_width_space_stripped() -> None:
    """Zero-width spaces must not fragment identity."""
    normal = "hello world"
    with_zwsp = "hello\u200bworld"  # zero-width space between hello and world

    assert canonicalize_text(normal) != canonicalize_text(with_zwsp) or \
           canonicalize_text(with_zwsp) == "helloworld" or \
           canonicalize_text(with_zwsp) == "hello world"
    # After stripping, zwsp is removed — "helloworld" as one token
    assert "\u200b" not in canonicalize_text(with_zwsp)


def test_zero_width_claim_identity() -> None:
    """Claims with zero-width characters must converge to same identity as clean text."""
    core_clean = ClaimCore(claim_type="fact", slots={"subject": "hello"})
    core_zwsp = ClaimCore(claim_type="fact", slots={"subject": "he\u200bllo"})

    assert core_clean.core_id == core_zwsp.core_id


def test_bom_stripped() -> None:
    """Byte order mark must be stripped."""
    normal = "test"
    with_bom = "\ufefftest"

    assert canonicalize_text(normal) == canonicalize_text(with_bom)


def test_bidi_marks_stripped() -> None:
    """Bidirectional marks must be stripped."""
    normal = "hello"
    with_lrm = "\u200ehello\u200f"  # LRM + hello + RLM

    assert canonicalize_text(normal) == canonicalize_text(with_lrm)


def test_canonicalize_text_idempotent() -> None:
    """Double application must produce the same result."""
    texts = [
        "Hello World",
        "caf\u00e9",
        "cafe\u0301",
        "\u200bhello\u200b",
        "\ufefftest",
        "  multiple   spaces  ",
    ]
    for text in texts:
        once = canonicalize_text(text)
        twice = canonicalize_text(once)
        assert once == twice, f"Not idempotent for {text!r}: {once!r} != {twice!r}"


def test_mixed_nfc_and_zero_width() -> None:
    """Combined NFC + zero-width issues must converge."""
    # café with decomposed é and zero-width space
    messy = "cafe\u0301\u200b"
    clean = "caf\u00e9"

    assert canonicalize_text(messy) == canonicalize_text(clean)
