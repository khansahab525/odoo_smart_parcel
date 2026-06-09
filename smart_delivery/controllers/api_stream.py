"""Real-time tracking stream via Server-Sent Events (SSE).

SSE provides WebSocket-like live updates over HTTP.
Flutter clients connect to /api/tracking/<id>/stream for push updates.
"""

import json
import logging
import time

from odoo import http
from odoo.http import request

from ..utils.event_utils import get_pending_events, mark_events_consumed
from .api_base import ApiBaseController

_logger = logging.getLogger(__name__)


class ApiStreamController(ApiBaseController):

    @http.route(
        '/api/tracking/<int:delivery_id>/stream',
        type='http', auth='public', methods=['GET'], csrf=False,
    )
    def tracking_stream(self, delivery_id, **kwargs):
        """SSE stream — pushes live tracking events to the client."""
        delivery = request.env['smart.delivery.order'].sudo().browse(delivery_id)
        if not delivery.exists():
            return self._json_response(error='Delivery not found', status=404)

        def generate():
            last_event_id = int(kwargs.get('last_event_id', 0))
            service = self._get_delivery_service()
            timeout = 120
            start = time.time()

            yield 'data: {"type":"connected","delivery_id":%d}\n\n' % delivery_id

            while time.time() - start < timeout:
                events = get_pending_events(
                    request.env, delivery_id, since_id=last_event_id,
                )
                if events:
                    for event in events:
                        payload = {
                            'id': event.id,
                            'type': event.event_type,
                            'payload': json.loads(event.payload or '{}'),
                            'timestamp': str(event.create_date),
                        }
                        yield 'id: %d\n' % event.id
                        yield 'data: %s\n\n' % json.dumps(payload, default=str)
                        last_event_id = event.id
                    mark_events_consumed(request.env, events.ids)
                else:
                    delivery.invalidate_recordset()
                    snapshot = service.serialize_delivery(delivery)
                    heartbeat = {
                        'type': 'heartbeat',
                        'delivery': snapshot,
                    }
                    yield 'data: %s\n\n' % json.dumps(heartbeat, default=str)

                time.sleep(3)

            yield 'data: {"type":"stream_end"}\n\n'

        return request.make_response(
            generate(),
            headers=[
                ('Content-Type', 'text/event-stream'),
                ('Cache-Control', 'no-cache'),
                ('Connection', 'keep-alive'),
                ('X-Accel-Buffering', 'no'),
            ],
        )

    @http.route(
        '/api/tracking/<int:delivery_id>/poll',
        type='http', auth='public', methods=['GET'], csrf=False,
    )
    def tracking_poll(self, delivery_id, **kwargs):
        """Long-poll endpoint — returns new events since last_event_id."""
        delivery = request.env['smart.delivery.order'].sudo().browse(delivery_id)
        if not delivery.exists():
            return self._json_response(error='Delivery not found', status=404)

        last_event_id = int(kwargs.get('last_event_id', 0))
        wait_seconds = min(int(kwargs.get('timeout', 25)), 30)
        start = time.time()

        while time.time() - start < wait_seconds:
            events = get_pending_events(
                request.env, delivery_id, since_id=last_event_id,
            )
            if events:
                result = []
                for event in events:
                    result.append({
                        'id': event.id,
                        'type': event.event_type,
                        'payload': json.loads(event.payload or '{}'),
                        'timestamp': str(event.create_date),
                    })
                    last_event_id = event.id
                mark_events_consumed(request.env, events.ids)
                return self._json_response(data={
                    'events': result,
                    'last_event_id': last_event_id,
                })
            time.sleep(1)

        service = self._get_delivery_service()
        return self._json_response(data={
            'events': [],
            'last_event_id': last_event_id,
            'delivery': service.serialize_delivery(delivery),
        })
