import pytest

from mcpserver.loxone.project.models import ProjectError, ProjectLimits
from mcpserver.loxone.project.parser import parse_project


def test_preserves_duplicate_attributes_and_mixed_content():
    parsed = parse_project(
        b'<P><C U="one" Serial="a" Serial="b" Phn="line\nnext">before<X/>after</C></P>'
    )
    item = parsed.elements[1]
    assert item.value("Serial") is None
    assert item.value("U") == "one"
    assert item.content == ("before", 2, "after")
    assert parsed.anomalies == ((1, "duplicate_attribute"), (1, "attribute_newline"))


def test_quotes_entities_and_unknown_elements():
    parsed = parse_project(b'<Unknown V="a > b &amp; c">&#x41;<![CDATA[<raw>]]></Unknown>')
    assert parsed.elements[0].value("V") == "a > b & c"
    assert parsed.elements[0].content == ("A", "<raw>")


@pytest.mark.parametrize(
    "data",
    [
        b"<!DOCTYPE P><P/>",
        b'<P a="&external;"/>',
        b"<P><C></P>",
        b"<P/><P/>",
        b"<P",
        b"<P bad/>",
        b'<P a="\x00"/>',
        b"<P>&bad</P>",
    ],
)
def test_rejects_unsafe_or_malformed_xml(data):
    with pytest.raises(ProjectError):
        parse_project(data)


def test_limits_apply_before_unbounded_model_growth():
    with pytest.raises(ProjectError, match="parse_limit"):
        parse_project(b"<P><C/></P>", ProjectLimits(elements=1))
    with pytest.raises(ProjectError, match="parse_limit"):
        parse_project(b"<P><C/></P>", ProjectLimits(depth=1))
    with pytest.raises(ProjectError, match="parse_limit"):
        parse_project(b'<P a="1" b="2"/>', ProjectLimits(attributes=1))
