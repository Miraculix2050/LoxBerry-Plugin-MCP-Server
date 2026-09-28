import pytest

from mcpserver.loxone.project.taxonomy import parse_taxonomy


def test_taxonomy_accepts_canonical_prefixes_and_sorts_them():
    entries = parse_taxonomy(
        [
            {"prefix": "6/2/7", "label": "One"},
            {"prefix": "6", "label": "All"},
            {"prefix": "6/2", "label": "Middle"},
        ]
    )
    assert [item.prefix for item in entries] == ["6", "6/2", "6/2/7"]


@pytest.mark.parametrize(
    "prefix",
    ["06/2", "6/02", "32", "6/8/1", "6/2/256", "6/2048", "6/2/1/0", "x/2"],
)
def test_taxonomy_rejects_invalid_prefix(prefix):
    with pytest.raises(ValueError):
        parse_taxonomy([{"prefix": prefix, "label": "Example"}])


def test_taxonomy_rejects_duplicates_and_control_characters():
    with pytest.raises(ValueError):
        parse_taxonomy(
            [
                {"prefix": "6/2", "label": "One"},
                {"prefix": "6/2", "label": "Two"},
            ]
        )
    with pytest.raises(ValueError):
        parse_taxonomy([{"prefix": "6", "label": "Bad\nlabel"}])
