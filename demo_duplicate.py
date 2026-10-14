#testing tool: sends an order event again to show the consumer skips duplicates
#run with: python demo_duplicate.py <order_id> <customer_id> <status>
import sys
from events import publish_order_event

order_id = int(sys.argv[1])
customer_id = int(sys.argv[2])
status = sys.argv[3]

publish_order_event({
    "event_id": f"order-{order_id}-{status}",
    "type": "order_status_changed",
    "order_id": order_id,
    "customer_id": customer_id,
    "old_status": None,
    "new_status": status,
})