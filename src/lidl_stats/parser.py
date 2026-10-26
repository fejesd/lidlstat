"""Turn a Lidl Plus receipt detail response into line items.

Two response shapes exist:
- v3: ``htmlPrintedReceipt`` - the printed receipt as HTML, items carried in
  ``data-art-*`` attributes on ``<span class="article">`` elements.
- v2 (older): ``itemsLine`` - a JSON list with names, prices and discounts.

The format is undocumented and country-specific, so parsing is best-effort. The raw
response is always stored, so receipts can be re-parsed after a parser fix.
"""

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any

_NUMBER_RE = re.compile(r"^-?\d+(?:[.,]\d+)?$")
_LINE_BREAK_TAGS = {"br", "div", "p", "tr", "li", "pre"}


@dataclass
class ParsedItem:
    name: str
    amount: float
    quantity: float = 1.0
    unit_price: float | None = None
    discount: float = 0.0
    code: str = ""
    is_weight: bool = False


@dataclass
class ParsedReceipt:
    source: str  # "html", "json" or "none"
    items: list[ParsedItem] = field(default_factory=list)


def parse_number(value: object) -> float | None:
    """Parse '1,99', '1.99', '1 299', '-0,50 Ft', 1299 into a float."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    text = re.sub(r"[^\d,.\-]", "", str(value))
    if not text or text in {"-", ",", "."}:
        return None
    if "," in text and "." in text:
        # Whichever separator comes last is the decimal one: 1.299,50 / 1,299.50
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    else:
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


class _HtmlReceiptParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.items: list[ParsedItem] = []
        self._line = 0
        self._last_key: tuple[int, str, str] | None = None
        self._in_bold = False
        self._bold_text = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _LINE_BREAK_TAGS:
            self._line += 1
        if tag != "span":
            return
        attr = {k: v for k, v in attrs if v is not None}
        css = attr.get("class", "")
        if "article" in css.split() and "data-art-description" in attr:
            self._add_article(attr)
        if "css_bold" in css.split():
            self._in_bold = True
            self._bold_text = ""

    def handle_data(self, data: str) -> None:
        if "\n" in data:
            self._line += data.count("\n")
        if self._in_bold:
            self._bold_text += data

    def handle_endtag(self, tag: str) -> None:
        if tag != "span" or not self._in_bold:
            return
        self._in_bold = False
        text = self._bold_text.strip()
        compact = re.sub(r"\s|Ft|HUF|€", "", text)  # \s also matches NBSP
        if _NUMBER_RE.match(compact):
            value = parse_number(compact)
            # A negative amount right after an article is a discount/coupon on that article.
            if value is not None and value < 0 and self.items:
                self.items[-1].discount = round(self.items[-1].discount - value, 2)

    def _add_article(self, attr: dict[str, str]) -> None:
        name = attr["data-art-description"].strip()
        code = attr.get("data-art-id", "")
        # The same article is rendered as several spans (name, price...) on one line.
        key = (self._line, code, name)
        if key == self._last_key:
            return
        self._last_key = key
        quantity = parse_number(attr.get("data-art-quantity"))
        unit_price = parse_number(attr.get("data-unit-price")) or 0.0
        if quantity is not None:
            amount = round(quantity * unit_price, 2)
            is_weight = not quantity.is_integer()
        else:
            quantity, amount, is_weight = 1.0, unit_price, False
        self.items.append(
            ParsedItem(
                name=name,
                amount=amount,
                quantity=quantity,
                unit_price=unit_price,
                code=code,
                is_weight=is_weight,
            )
        )


def _parse_html(html: str) -> list[ParsedItem]:
    parser = _HtmlReceiptParser()
    parser.feed(html)
    parser.close()
    return parser.items


def _parse_items_line(lines: list[dict[str, Any]]) -> list[ParsedItem]:
    items: list[ParsedItem] = []
    for line in lines:
        name = str(line.get("name") or "").strip()
        if not name:
            continue
        quantity = parse_number(line.get("quantity")) or 1.0
        unit_price = parse_number(line.get("currentUnitPrice"))
        amount = parse_number(line.get("originalAmount"))
        if amount is None:
            amount = round(quantity * (unit_price or 0.0), 2)
        discount = sum(
            abs(parse_number(d.get("amount")) or 0.0) for d in line.get("discounts") or []
        )
        items.append(
            ParsedItem(
                name=name,
                amount=amount,
                quantity=quantity,
                unit_price=unit_price,
                discount=round(discount, 2),
                code=str(line.get("codeInput") or ""),
                is_weight=bool(line.get("isWeight")),
            )
        )
    return items


def parse_receipt(detail: dict[str, Any]) -> ParsedReceipt:
    html = detail.get("htmlPrintedReceipt")
    if isinstance(html, str) and html:
        items = _parse_html(html)
        if items:
            return ParsedReceipt("html", items)
    lines = detail.get("itemsLine")
    if isinstance(lines, list) and lines:
        return ParsedReceipt("json", _parse_items_line(lines))
    return ParsedReceipt("none")
