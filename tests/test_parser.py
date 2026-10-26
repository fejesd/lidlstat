from pathlib import Path

import pytest

from lidl_stats.parser import parse_number, parse_receipt

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1,99", 1.99),
        ("1.99", 1.99),
        ("1 299", 1299.0),
        ("1.299,50", 1299.5),
        ("1,299.50", 1299.5),
        ("-0,50 Ft", -0.5),
        (1299, 1299.0),
        ("", None),
        (None, None),
    ],
)
def test_parse_number(raw: object, expected: float | None) -> None:
    assert parse_number(raw) == expected


def test_parse_html_receipt() -> None:
    html = (FIXTURES / "receipt_v3.html").read_text()
    parsed = parse_receipt({"htmlPrintedReceipt": html})
    assert parsed.source == "html"
    assert [i.name for i in parsed.items] == ["TEJ 2,8% 1L", "TEJ 2,8% 1L", "BANÁN", "KENYÉR"]
    milk, _, banana, bread = parsed.items
    assert milk.amount == 329.0
    assert banana.is_weight and banana.amount == 739.77
    assert banana.discount == 100.0
    assert bread.quantity == 2 and bread.amount == 898.0 and not bread.is_weight


def test_parse_items_line() -> None:
    detail = {
        "itemsLine": [
            {
                "name": "Vegane Frikadellen",
                "currentUnitPrice": "2,19",
                "quantity": "1",
                "originalAmount": "2,19",
                "isWeight": False,
                "codeInput": "4023456245134",
                "discounts": [{"description": "5€ Coupon", "amount": "0,21"}],
            },
            {"name": "Paradicsom", "currentUnitPrice": "3,49", "quantity": "0,5", "isWeight": True},
        ]
    }
    parsed = parse_receipt(detail)
    assert parsed.source == "json"
    first, second = parsed.items
    assert (first.amount, first.discount, first.code) == (2.19, 0.21, "4023456245134")
    assert second.amount == 1.75 and second.is_weight


def test_parse_empty() -> None:
    assert parse_receipt({}).source == "none"
