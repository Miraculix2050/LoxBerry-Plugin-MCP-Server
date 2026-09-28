import pytest

from mcpserver.loxone.project.taxonomy import parse_taxonomy


def test_taxonomy_accepts_canonical_prefixes_and_sorts_them():
    entries = parse_taxonomy(
        [
            {"address_format": "three_level", "prefix": "6/2/7", "label": "One"},
            {"address_format": "three_level", "prefix": "6", "label": "All"},
            {"address_format": "three_level", "prefix": "6/2", "label": "Middle"},
        ]
    )
    assert [item.prefix for item in entries] == ["6", "6/2", "6/2/7"]


@pytest.mark.parametrize(
    "prefix",
    ["06/2", "6/02", "32", "6/8/1", "6/2/256", "6/2048", "6/2/1/0", "x/2"],
)
def test_taxonomy_rejects_invalid_prefix(prefix):
    with pytest.raises(ValueError):
        parse_taxonomy([{"address_format": "three_level", "prefix": prefix, "label": "Example"}])


def test_taxonomy_rejects_duplicates_and_control_characters():
    with pytest.raises(ValueError):
        parse_taxonomy(
            [
                {"address_format": "three_level", "prefix": "6/2", "label": "One"},
                {"address_format": "three_level", "prefix": "6/2", "label": "Two"},
            ]
        )
    with pytest.raises(ValueError):
        parse_taxonomy([{"address_format": "three_level", "prefix": "6", "label": "Bad\nlabel"}])


def test_taxonomy_requires_format_and_accepts_same_numbers_in_both_formats():
    with pytest.raises(ValueError):
        parse_taxonomy([{"prefix": "6/2", "label": "Ambiguous"}])
    with pytest.raises(ValueError):
        parse_taxonomy([{"address_format": [], "prefix": "6/2", "label": "Invalid"}])
    entries = parse_taxonomy(
        [
            {"address_format": "two_level", "prefix": "6/2", "label": "Two"},
            {"address_format": "three_level", "prefix": "6/2", "label": "Three"},
        ]
    )
    assert {(item.address_format, item.label) for item in entries} == {
        ("two_level", "Two"),
        ("three_level", "Three"),
    }
