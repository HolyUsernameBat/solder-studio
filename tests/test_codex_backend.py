from studio.codex_backend import status_from_event, subscription_from_status


def test_chatgpt_subscription_status_is_recognized():
    assert subscription_from_status("Logged in using ChatGPT\n")


def test_api_key_login_is_not_the_subscription():
    assert not subscription_from_status("Logged in using an API key\n")
    assert not subscription_from_status("Not logged in\n")


def test_status_from_event_maps_known_types():
    assert status_from_event({"type": "turn.started"}) == "Turn started."
    assert status_from_event({"type": "turn.completed"}) == "Turn finished."
    msg = status_from_event(
        {
            "type": "item.completed",
            "item": {"id": "1", "type": "agent_message", "text": "Extracting rows."},
        }
    )
    assert msg == "Extracting rows."
    assert status_from_event({"type": "thread.started", "thread_id": "abc"}) is None
    assert status_from_event({"type": "item.started", "item": {"type": "reasoning"}}) is None
