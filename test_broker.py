import broker


class FakeConnection:
    is_open = True

    def close(self):
        self.is_open = False


class FakeChannel:
    def basic_publish(self, **kwargs):
        return None


def test_publish_order_event_treats_confirmed_none_as_success(monkeypatch):
    connection = FakeConnection()
    monkeypatch.setattr(
        broker, "open_channel", lambda: (connection, FakeChannel())
    )

    assert broker.publish_order_event("event-1", "order.created", {}) is True
    assert connection.is_open is False
