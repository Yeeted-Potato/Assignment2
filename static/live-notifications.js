(function() {
    const role = document.currentScript.dataset.role;
    const customerApi = window.location.protocol + "//" +
        window.location.hostname + ":8000";
    const staffApi = window.location.protocol + "//" +
        window.location.hostname + ":8001";
    const api = role === "staff" ? staffApi : customerApi;
    const panel = document.createElement("aside");
    panel.id = "liveNotificationsPanel";
    panel.innerHTML =
        '<h2>Order notifications</h2>' +
        '<p class="notification-help">Saved alerts include earlier orders; times are New Zealand time.</p>' +
        '<p id="liveNotificationsStatus" role="status">Connecting...</p>' +
        '<ul id="liveNotificationsList" aria-live="polite"></ul>';

    const style = document.createElement("style");
    style.textContent =
        "body{padding-right:340px!important}" +
        "#liveNotificationsPanel{box-sizing:border-box;position:fixed;z-index:1000;" +
        "top:16px;right:16px;width:308px;max-height:calc(100vh - 32px);overflow:auto;" +
        "padding:16px;background:#fff;border:1px solid #d1d5db;border-radius:10px;" +
        "box-shadow:0 5px 18px #0002;font:14px Arial,sans-serif;color:#1f2937}" +
        "#liveNotificationsPanel h2{font-size:18px;margin:0 0 8px}" +
        ".notification-help{font-size:12px;color:#4b5563;margin:0 0 8px}" +
        "#liveNotificationsStatus{font-size:13px;color:#4b5563}" +
        "#liveNotificationsList{padding-left:20px;margin-bottom:0}" +
        "#liveNotificationsList li{padding:9px 0;border-bottom:1px solid #e5e7eb}" +
        "@media(max-width:760px){body{padding-right:0!important}" +
        "#liveNotificationsPanel{position:static;width:auto;max-height:300px;margin:16px}}";
    document.head.appendChild(style);
    document.body.appendChild(panel);

    const status = document.getElementById("liveNotificationsStatus");
    const list = document.getElementById("liveNotificationsList");
    const seen = new Set();
    let reconnectDelay = 1000;
    let reconnectTimer;
    let socket;
    let customerSocket;
    let customerSocketConnected = false;
    let customerId = role === "customer"
        ? localStorage.getItem("customerId")
        : null;

    function addNotification(id, message, eventTimestamp, restored) {
        if (id && seen.has(id)) {
            return;
        }
        if (id) {
            seen.add(id);
        }
        const item = document.createElement("li");
        const cleanMessage = message.replace(/[.!?]+$/, "");
        if (restored) {
            const savedEventTime = eventTimestamp
                ? formatNewZealandTime(eventTimestamp)
                : "unavailable";
            item.textContent =
                "Event occurred at " + savedEventTime + " — " + cleanMessage + ".";
        } else {
            const notifiedTime = formatNewZealandTime(new Date().toISOString());
            const eventTime = eventTimestamp
                ? formatNewZealandTime(eventTimestamp)
                : "unavailable";
            item.textContent =
                "Notified at " + notifiedTime + " — " + cleanMessage +
                "; event occurred at " + eventTime + ".";
        }
        list.prepend(item);
        while (list.children.length > 25) {
            list.lastElementChild.remove();
        }
    }

    function formatNewZealandTime(timestamp) {
        const normalized = /(?:Z|[+-]\d{2}:\d{2})$/.test(timestamp)
            ? timestamp
            : timestamp + "Z";
        return new Intl.DateTimeFormat("en-NZ", {
            year: "numeric",
            month: "short",
            day: "numeric",
            hour: "numeric",
            minute: "2-digit",
            second: "2-digit",
            timeZone: "Pacific/Auckland"
        }).format(new Date(normalized));
    }

    async function restoreNotifications() {
        if (role === "customer" && !customerId) {
            status.textContent = "Sign in to see your saved order notifications.";
            return;
        }
        try {
            const path = role === "staff"
                ? "/staff/notifications"
                : "/customers/" + customerId + "/notifications";
            const response = await fetch(api + path);
            if (!response.ok) {
                throw new Error("Notification request returned " + response.status);
            }
            const notifications = await response.json();
            list.replaceChildren();
            seen.clear();
            for (const notification of notifications.reverse()) {
                addNotification(
                    notification.event_id,
                    notification.message,
                    notification.created_at,
                    true
                );
            }
        } catch (error) {
            status.textContent = "Could not restore notifications. Reconnecting will retry.";
        }
    }

    function showCustomerEvent(event) {
        const payload = event.payload || {};
        const currentId = Number(customerId);
        if (event.event_type === "inventory.updated") {
            window.dispatchEvent(new CustomEvent("order-created-live", {
                detail: payload
            }));
        } else if (event.event_type === "order.created") {
            if (payload.customer_id === currentId) {
                addNotification(
                    event.event_id,
                    "Your order #" + payload.order_id + " was placed.",
                    event.occurred_at,
                    false
                );
            }
        } else if (
            event.event_type === "order.status_changed" &&
            payload.customer_id === currentId
        ) {
            addNotification(
                event.event_id,
                "Order #" + payload.order_id + " changed to " + payload.new_status + ".",
                event.occurred_at,
                false
            );
            window.dispatchEvent(new CustomEvent("customer-order-status-live", {
                detail: payload
            }));
        }
    }

    function connectInventorySocket() {
        const scheme = window.location.protocol === "https:" ? "wss:" : "ws:";
        const url = scheme + "//" + window.location.hostname +
            ":8000/ws/customer-updates";
        const inventorySocket = new WebSocket(url);
        inventorySocket.onopen = function() {
            status.textContent = customerId
                ? "Live order updates connected."
                : "Live product availability connected. Sign in for personal alerts.";
            window.dispatchEvent(new CustomEvent("order-created-live", {
                detail: { refresh: true }
            }));
        };
        inventorySocket.onmessage = function(message) {
            const event = JSON.parse(message.data);
            if (event.event_type === "inventory.updated") {
                showCustomerEvent(event);
            }
        };
        inventorySocket.onclose = function() {
            status.textContent = "Live updates disconnected. Reconnecting...";
            setTimeout(connectInventorySocket, 2000);
        };
        inventorySocket.onerror = function() {
            inventorySocket.close();
        };
    }

    function connectCustomerSocket() {
        if (!customerId) {
            return;
        }
        if (customerSocket) {
            customerSocket.onclose = null;
            customerSocket.close();
        }
        const scheme = window.location.protocol === "https:" ? "wss:" : "ws:";
        customerSocket = new WebSocket(
            scheme + "//" + window.location.hostname + ":8000/ws/customers/" +
            customerId + "/orders"
        );
        customerSocket.onmessage = function(message) {
            showCustomerEvent(JSON.parse(message.data));
        };
        customerSocket.onopen = function() {
            status.textContent = "Live order updates connected.";
            if (customerSocketConnected) {
                restoreNotifications();
            }
            customerSocketConnected = true;
        };
        customerSocket.onclose = function() {
            status.textContent = "Live updates disconnected. Reconnecting...";
            setTimeout(connectCustomerSocket, 2000);
        };
        customerSocket.onerror = function() {
            customerSocket.close();
        };
    }

    function connectStaffSocket() {
        const scheme = window.location.protocol === "https:" ? "wss:" : "ws:";
        socket = new WebSocket(
            scheme + "//" + window.location.hostname + ":8001/ws/staff/orders"
        );
        status.textContent = "Connecting to live order notifications...";
        socket.onopen = function() {
            reconnectDelay = 1000;
            status.textContent = "Live order notifications connected.";
            restoreNotifications();
        };
        socket.onmessage = function(message) {
            const event = JSON.parse(message.data);
            if (event.event_type !== "order.created") {
                return;
            }
            const order = event.payload;
            addNotification(
                event.event_id,
                "New order #" + order.order_id + " from " +
                    order.customer_name + ": " + order.quantity +
                    " x " + order.product_name,
                event.occurred_at,
                false
            );
            status.textContent = "Order notification received; check its timestamp.";
            window.dispatchEvent(new CustomEvent("order-created-live", {
                detail: order
            }));
        };
        socket.onclose = function() {
            status.textContent = "Live connection lost. Reconnecting...";
            clearTimeout(reconnectTimer);
            reconnectTimer = setTimeout(connectStaffSocket, reconnectDelay);
            reconnectDelay = Math.min(reconnectDelay * 2, 15000);
        };
        socket.onerror = function() {
            socket.close();
        };
    }

    if (role === "staff") {
        connectStaffSocket();
    } else {
        connectInventorySocket();
        if (customerId) {
            restoreNotifications();
            connectCustomerSocket();
        }
        window.addEventListener("customer-login-live", function(event) {
            customerId = String(event.detail.id);
            restoreNotifications();
            connectCustomerSocket();
        });
        window.addEventListener("customer-order-status-live", function() {
            const statusLabel = document.getElementById("liveConnectionStatus");
            if (statusLabel) {
                statusLabel.textContent = "Your order status was updated live.";
            }
        });
    }
})();
