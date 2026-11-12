"""Hash layer: standard vectors plus the field-id derivation."""

import pytest

from ootsw2.hash import field_id, murmur3_32


@pytest.mark.parametrize(
    "data, seed, expected",
    [
        (b"", 0, 0x00000000),
        (b"", 1, 0x514E28B7),
        (b"hello", 0, 0x248BFA47),
        (b"hello, world", 0, 0x149BBB7F),
        (b"abc", 0, 0xB3DD93FA),
        (b"The quick brown fox jumps over the lazy dog", 0, 0x2E4FF723),
    ],
)
def test_murmur3_matches_reference_vectors(data, seed, expected):
    assert murmur3_32(data, seed) == expected


def test_murmur3_is_32_bit():
    for payload in (b"a", b"ab", b"abc", b"x" * 64):
        assert 0 <= murmur3_32(payload) <= 0xFFFFFFFF


@pytest.mark.parametrize(
    "name, expected",
    [
        ("PlayerStatus.DiveDepth", 1632005153),
        ("PlayerStatus.CurrentRupee", 2809733591),
        ("PouchData.Item_Scale_Gold.StockNum", 1256920074),
        ("PlayerStatus.EquipWeapon", 2841261345),
    ],
)
def test_field_id_matches_observed_keys(name, expected):
    """These ids were read straight out of a real save file."""
    assert field_id(name) == expected


def test_field_id_rejects_bad_input():
    with pytest.raises(ValueError):
        field_id("")
    with pytest.raises(TypeError):
        field_id(b"PlayerStatus.Life")
