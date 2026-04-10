"""Unit tests for the serialize module.

The serializers walk amazon-orders entity objects with plain `getattr`,
so we can feed them `SimpleNamespace` stubs and avoid pulling in the
real (BeautifulSoup-backed) library types.
"""

from datetime import date, datetime
from types import SimpleNamespace

from amazon_orders_mcp.serialize import (
    _d,
    serialize_item,
    serialize_order,
    serialize_orders,
    serialize_recipient,
    serialize_seller,
    serialize_shipment,
    serialize_transaction,
    serialize_transactions,
)


class TestDateHelper:
    def test_none_passthrough(self):
        assert _d(None) is None

    def test_date_iso(self):
        assert _d(date(2026, 4, 10)) == "2026-04-10"

    def test_datetime_iso(self):
        assert _d(datetime(2026, 4, 10, 12, 30, 45)) == "2026-04-10T12:30:45"

    def test_other_stringified(self):
        assert _d("already a string") == "already a string"


class TestSellerAndRecipient:
    def test_seller_none(self):
        assert serialize_seller(None) is None

    def test_seller_basic(self):
        seller = SimpleNamespace(name="Acme", link="https://acme.example")
        assert serialize_seller(seller) == {
            "name": "Acme",
            "link": "https://acme.example",
        }

    def test_seller_missing_attrs(self):
        assert serialize_seller(SimpleNamespace()) == {"name": None, "link": None}

    def test_recipient_none(self):
        assert serialize_recipient(None) is None

    def test_recipient_basic(self):
        r = SimpleNamespace(name="Jane Doe", address="1 Infinite Loop")
        assert serialize_recipient(r) == {
            "name": "Jane Doe",
            "address": "1 Infinite Loop",
        }


class TestSerializeItem:
    def test_full_item(self):
        item = SimpleNamespace(
            title="Widget",
            link="https://amazon.example/dp/W",
            price=12.99,
            quantity=2,
            condition="new",
            return_eligible_date=date(2026, 5, 1),
            image_link="https://img.example/w.jpg",
            seller=SimpleNamespace(name="WidgetCo", link="https://widgetco.example"),
        )
        assert serialize_item(item) == {
            "title": "Widget",
            "link": "https://amazon.example/dp/W",
            "price": 12.99,
            "quantity": 2,
            "condition": "new",
            "return_eligible_date": "2026-05-01",
            "image_link": "https://img.example/w.jpg",
            "seller": {"name": "WidgetCo", "link": "https://widgetco.example"},
        }

    def test_missing_attrs(self):
        result = serialize_item(SimpleNamespace())
        assert result["title"] is None
        assert result["seller"] is None
        assert result["return_eligible_date"] is None


class TestSerializeShipment:
    def test_empty_items(self):
        s = SimpleNamespace(delivery_status="Delivered", tracking_link=None, items=None)
        result = serialize_shipment(s)
        assert result["delivery_status"] == "Delivered"
        assert result["items"] == []

    def test_with_items(self):
        item = SimpleNamespace(title="Thing", price=5.0)
        s = SimpleNamespace(
            delivery_status="In transit",
            tracking_link="https://track.example",
            items=[item],
        )
        result = serialize_shipment(s)
        assert len(result["items"]) == 1
        assert result["items"][0]["title"] == "Thing"


class TestSerializeOrder:
    def test_basic_order_no_full_details(self):
        order = SimpleNamespace(
            order_number="111-2222222-3333333",
            order_placed_date=date(2026, 3, 1),
            grand_total=42.00,
            order_details_link="https://amazon.example/order/111",
            full_details=False,
            recipient=SimpleNamespace(name="Me", address="123 Main"),
            items=[SimpleNamespace(title="A")],
            shipments=[],
        )
        result = serialize_order(order)
        assert result["order_number"] == "111-2222222-3333333"
        assert result["order_placed_date"] == "2026-03-01"
        assert result["grand_total"] == 42.00
        assert result["full_details"] is False
        # Full-detail fields should NOT be present
        assert "payment_method" not in result
        assert "subtotal" not in result

    def test_full_details_includes_extra_fields(self):
        order = SimpleNamespace(
            order_number="111-2222222-3333333",
            order_placed_date=date(2026, 3, 1),
            grand_total=42.00,
            order_details_link=None,
            full_details=True,
            recipient=None,
            items=[],
            shipments=[],
            payment_method="Visa",
            payment_method_last_4="4242",
            subtotal=40.00,
            shipping_total=0.00,
            free_shipping=True,
            promotion_applied=None,
            coupon_savings=None,
            reward_points=None,
            subscription_discount=None,
            total_before_tax=40.00,
            estimated_tax=2.00,
            refund_total=None,
            multibuy_discount=None,
            amazon_discount=None,
            gift_card=None,
            gift_wrap=False,
        )
        result = serialize_order(order)
        assert result["full_details"] is True
        assert result["payment_method"] == "Visa"
        assert result["payment_method_last_4"] == "4242"
        assert result["subtotal"] == 40.00
        assert result["estimated_tax"] == 2.00

    def test_none_items_and_shipments(self):
        order = SimpleNamespace(
            order_number="x",
            order_placed_date=None,
            grand_total=None,
            order_details_link=None,
            full_details=False,
            recipient=None,
            items=None,
            shipments=None,
        )
        result = serialize_order(order)
        assert result["items"] == []
        assert result["shipments"] == []

    def test_serialize_orders_list(self):
        orders = [
            SimpleNamespace(
                order_number="1",
                order_placed_date=None,
                grand_total=None,
                order_details_link=None,
                full_details=False,
                recipient=None,
                items=None,
                shipments=None,
            ),
            SimpleNamespace(
                order_number="2",
                order_placed_date=None,
                grand_total=None,
                order_details_link=None,
                full_details=False,
                recipient=None,
                items=None,
                shipments=None,
            ),
        ]
        result = serialize_orders(orders)
        assert [o["order_number"] for o in result] == ["1", "2"]


class TestSerializeTransaction:
    def test_basic(self):
        txn = SimpleNamespace(
            completed_date=date(2026, 3, 4),
            payment_method="Visa ending in 4242",
            grand_total=-35.01,
            is_refund=False,
            order_number="111-2222222-3333333",
            order_details_link="https://amazon.example/order/111",
            seller="Amazon.com",
        )
        result = serialize_transaction(txn)
        assert result == {
            "completed_date": "2026-03-04",
            "payment_method": "Visa ending in 4242",
            "grand_total": -35.01,
            "is_refund": False,
            "order_number": "111-2222222-3333333",
            "order_details_link": "https://amazon.example/order/111",
            "seller": "Amazon.com",
        }

    def test_none_date(self):
        txn = SimpleNamespace(
            completed_date=None,
            payment_method=None,
            grand_total=None,
            is_refund=None,
            order_number=None,
            order_details_link=None,
            seller=None,
        )
        assert serialize_transaction(txn)["completed_date"] is None

    def test_serialize_transactions_list(self):
        txns = [
            SimpleNamespace(
                completed_date=date(2026, 3, 1),
                payment_method=None,
                grand_total=-10.0,
                is_refund=False,
                order_number="a",
                order_details_link=None,
                seller=None,
            ),
            SimpleNamespace(
                completed_date=date(2026, 3, 2),
                payment_method=None,
                grand_total=20.0,
                is_refund=True,
                order_number="b",
                order_details_link=None,
                seller=None,
            ),
        ]
        result = serialize_transactions(txns)
        assert [t["order_number"] for t in result] == ["a", "b"]
