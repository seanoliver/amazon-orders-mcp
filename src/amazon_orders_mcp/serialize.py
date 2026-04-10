"""
Hand-rolled serialization for `amazon-orders` entity objects.

The library's entities do not expose `to_dict()` or `to_json()` methods, and
naive `json.dumps(obj.__dict__)` fails because the `parsed` BeautifulSoup Tag
is stored on every entity. We walk a known field list per entity type.
"""

from datetime import date, datetime
from typing import Any, Dict, List, Optional


def _d(value: Optional[Any]) -> Optional[str]:
    """ISO-format a date/datetime if present."""
    if value is None:
        return None
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def serialize_seller(seller: Optional[Any]) -> Optional[Dict[str, Any]]:
    if seller is None:
        return None
    return {
        "name": getattr(seller, "name", None),
        "link": getattr(seller, "link", None),
    }


def serialize_item(item: Any) -> Dict[str, Any]:
    """Serialize an Item entity."""
    return {
        "title": getattr(item, "title", None),
        "link": getattr(item, "link", None),
        "price": getattr(item, "price", None),
        "quantity": getattr(item, "quantity", None),
        "condition": getattr(item, "condition", None),
        "return_eligible_date": _d(getattr(item, "return_eligible_date", None)),
        "image_link": getattr(item, "image_link", None),
        "seller": serialize_seller(getattr(item, "seller", None)),
    }


def serialize_shipment(shipment: Any) -> Dict[str, Any]:
    """Serialize a Shipment entity."""
    items = getattr(shipment, "items", None) or []
    return {
        "delivery_status": getattr(shipment, "delivery_status", None),
        "tracking_link": getattr(shipment, "tracking_link", None),
        "items": [serialize_item(i) for i in items],
    }


def serialize_recipient(recipient: Optional[Any]) -> Optional[Dict[str, Any]]:
    if recipient is None:
        return None
    return {
        "name": getattr(recipient, "name", None),
        "address": getattr(recipient, "address", None),
    }


# Fields that are only populated when full_details=True
_FULL_DETAIL_FIELDS = (
    "payment_method",
    "payment_method_last_4",
    "subtotal",
    "shipping_total",
    "free_shipping",
    "promotion_applied",
    "coupon_savings",
    "reward_points",
    "subscription_discount",
    "total_before_tax",
    "estimated_tax",
    "refund_total",
    "multibuy_discount",
    "amazon_discount",
    "gift_card",
    "gift_wrap",
)


def serialize_order(order: Any) -> Dict[str, Any]:
    """Serialize an Order entity.

    Includes full-detail fields only if they were populated by the library.
    """
    items = getattr(order, "items", None) or []
    shipments = getattr(order, "shipments", None) or []
    result: Dict[str, Any] = {
        "order_number": getattr(order, "order_number", None),
        "order_placed_date": _d(getattr(order, "order_placed_date", None)),
        "grand_total": getattr(order, "grand_total", None),
        "order_details_link": getattr(order, "order_details_link", None),
        "full_details": getattr(order, "full_details", False),
        "recipient": serialize_recipient(getattr(order, "recipient", None)),
        "items": [serialize_item(i) for i in items],
        "shipments": [serialize_shipment(s) for s in shipments],
    }
    if result["full_details"]:
        for field in _FULL_DETAIL_FIELDS:
            result[field] = getattr(order, field, None)
    return result


def serialize_transaction(txn: Any) -> Dict[str, Any]:
    """Serialize a Transaction entity.

    NOTE: `grand_total` sign convention is inverted from typical bank data —
    charges are negative, refunds positive. We preserve the library's convention
    and add an `is_refund` flag for convenience.
    """
    grand_total = getattr(txn, "grand_total", None)
    return {
        "completed_date": _d(getattr(txn, "completed_date", None)),
        "payment_method": getattr(txn, "payment_method", None),
        "grand_total": grand_total,
        "is_refund": getattr(txn, "is_refund", None),
        "order_number": getattr(txn, "order_number", None),
        "order_details_link": getattr(txn, "order_details_link", None),
        "seller": getattr(txn, "seller", None),
    }


def serialize_orders(orders: List[Any]) -> List[Dict[str, Any]]:
    return [serialize_order(o) for o in orders]


def serialize_transactions(transactions: List[Any]) -> List[Dict[str, Any]]:
    return [serialize_transaction(t) for t in transactions]
