"""Real-time event broadcasting utilities."""

import json
import logging

_logger = logging.getLogger(__name__)


def broadcast_event(env, delivery, event_type, payload_dict):
    """Create a delivery event record for SSE/stream consumers."""
    Event = env['smart.delivery.event'].sudo()
    return Event.create({
        'delivery_id': delivery.id,
        'event_type': event_type,
        'payload': json.dumps(payload_dict, default=str),
    })


def get_pending_events(env, delivery_id, since_id=0, limit=50):
    """Fetch unconsumed events for a delivery since a given event ID."""
    domain = [
        ('delivery_id', '=', delivery_id),
        ('id', '>', since_id),
    ]
    events = env['smart.delivery.event'].sudo().search(
        domain, order='id asc', limit=limit,
    )
    return events


def mark_events_consumed(env, event_ids):
    """Mark events as consumed after streaming."""
    if event_ids:
        env['smart.delivery.event'].sudo().browse(event_ids).write({
            'is_consumed': True,
        })
