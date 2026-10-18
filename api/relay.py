"""The relay: forwards each extracted row from psd-events-tag to psd-events-tagged, so no consumer calls the model again.

flattenResult has already run on the subscription, so the delivered data is the finished tagged row and is forwarded
byte for byte. A failed publish returns False and the caller nacks (or answers 5xx to a push), so Pub/Sub redelivers;
event_id absorbs the duplicate that a redelivery can cause downstream.
"""

from api.publish import publish

SUBSCRIPTION = "psd-events-tag"
TOPIC = "psd-events-tagged"


def relay(data: bytes, attributes: dict[str, str], message_id: str) -> bool:
    attrs = dict(attributes)
    event_id = attrs.pop("event_id", "")
    source = attrs.pop("source", "")
    return (
        publish(
            TOPIC,
            data,
            event_id,
            source,
            keep_failure=False,
            relay_message_id=message_id,
            **attrs,
        )
        is not None
    )
