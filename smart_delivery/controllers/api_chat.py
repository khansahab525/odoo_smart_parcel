import logging

from odoo import http
from odoo.http import request

from .api_base import ApiBaseController

_logger = logging.getLogger(__name__)


class ApiChatController(ApiBaseController):

    @http.route('/api/chat', type='http', auth='public', methods=['POST'], csrf=False)
    def chat(self, **kwargs):
        """AI chatbot endpoint — OpenAI generates human-readable responses."""
        body = self._parse_json_body()
        delivery_id = body.get('delivery_id')
        message = body.get('message', '').strip()

        if not delivery_id:
            return self._json_response(error='delivery_id required', status=400)
        if not message:
            return self._json_response(error='message required', status=400)

        delivery = request.env['smart.delivery.order'].sudo().browse(int(delivery_id))
        if not delivery.exists():
            return self._json_response(error='Delivery not found', status=404)

        service = self._get_delivery_service()
        try:
            response_text = service.get_chat_response(delivery, message)
            return self._json_response(data={
                'delivery_id': delivery.id,
                'message': message,
                'response': response_text,
                'delivery_status': delivery.status,
                'eta_minutes': delivery.eta_minutes,
                'delay_status': delivery.delay_status,
            })
        except Exception as exc:
            _logger.exception('Chat failed')
            return self._json_response(error=str(exc), status=500)

    @http.route(
        '/api/notification/generate',
        type='http', auth='public', methods=['POST'], csrf=False
    )
    def generate_notification(self, **kwargs):
        """Generate a smart notification for a delivery event."""
        body = self._parse_json_body()
        delivery_id = body.get('delivery_id')
        event_type = body.get('event_type', 'update')

        if not delivery_id:
            return self._json_response(error='delivery_id required', status=400)

        delivery = request.env['smart.delivery.order'].sudo().browse(int(delivery_id))
        if not delivery.exists():
            return self._json_response(error='Delivery not found', status=404)

        service = self._get_delivery_service()
        try:
            notification = service.get_notification(delivery, event_type)
            return self._json_response(data={
                'delivery_id': delivery.id,
                'event_type': event_type,
                'notification': notification,
            })
        except Exception as exc:
            _logger.exception('Notification generation failed')
            return self._json_response(error=str(exc), status=500)
