import logging

from odoo import http
from odoo.http import request

from .api_base import ApiBaseController

_logger = logging.getLogger(__name__)


class ApiDeliveryController(ApiBaseController):

    @http.route('/api/delivery/create', type='http', auth='public', methods=['POST'], csrf=False)
    def create_delivery(self, **kwargs):
        body = self._parse_json_body()
        service = self._get_delivery_service()

        required = ['customer_name', 'pickup_lat', 'pickup_lng', 'delivery_lat', 'delivery_lng']
        missing = [f for f in required if body.get(f) is None]
        if missing:
            return self._json_response(
                error=f'Missing required fields: {", ".join(missing)}', status=400
            )

        try:
            if body.get('customer_user_id'):
                body['customer_user_id'] = int(body['customer_user_id'])
            delivery = service.create_delivery(body)
            if body.get('driver_id'):
                service.assign_driver(delivery, body['driver_id'])
            return self._json_response(
                data=service.serialize_delivery(delivery), status=201
            )
        except Exception as exc:
            _logger.exception('Create delivery failed')
            return self._json_response(error=str(exc), status=500)

    @http.route('/api/delivery/<int:delivery_id>', type='http', auth='public', methods=['GET'], csrf=False)
    def get_delivery(self, delivery_id, **kwargs):
        service = self._get_delivery_service()
        delivery = request.env['smart.delivery.order'].sudo().browse(delivery_id)
        if not delivery.exists():
            return self._json_response(error='Delivery not found', status=404)
        return self._json_response(data=service.serialize_delivery(delivery))

    @http.route('/api/delivery/list', type='http', auth='public', methods=['GET'], csrf=False)
    def list_deliveries(self, **kwargs):
        service = self._get_delivery_service()
        user_id = kwargs.get('user_id')
        domain = []

        if user_id:
            user = self._get_user_by_id(user_id)
            if not user:
                return self._json_response(error='User not found', status=404)

            role = user.smart_delivery_role or 'customer'
            is_admin = role == 'admin' or user.has_group('base.group_system')

            if is_admin:
                domain = []
            elif role == 'driver':
                if user.smart_driver_id:
                    domain = [('driver_id', '=', user.smart_driver_id.id)]
                else:
                    domain = [('id', '=', 0)]
            elif role == 'customer':
                clauses = [('customer_user_id', '=', user.id)]
                if user.smart_customer_phone:
                    clauses = [
                        '|',
                        ('customer_user_id', '=', user.id),
                        ('customer_phone', '=', user.smart_customer_phone),
                    ]
                domain = clauses
            else:
                domain = []

        status_filter = kwargs.get('status')
        if status_filter:
            domain.append(('status', '=', status_filter))

        deliveries = request.env['smart.delivery.order'].sudo().search(domain)
        return self._json_response(data=[
            service.serialize_delivery(d) for d in deliveries
        ])

    @http.route(
        '/api/delivery/<int:delivery_id>/status',
        type='http', auth='public', methods=['POST'], csrf=False
    )
    def update_status(self, delivery_id, **kwargs):
        body = self._parse_json_body()
        new_status = body.get('status')
        if not new_status:
            return self._json_response(error='status field required', status=400)

        service = self._get_delivery_service()
        delivery = request.env['smart.delivery.order'].sudo().browse(delivery_id)
        if not delivery.exists():
            return self._json_response(error='Delivery not found', status=404)

        valid_statuses = [
            'created', 'assigned', 'picked_up', 'in_transit',
            'out_for_delivery', 'delivered', 'cancelled',
        ]
        if new_status not in valid_statuses:
            return self._json_response(
                error=f'Invalid status. Must be one of: {valid_statuses}', status=400,
            )

        try:
            service.update_status(delivery, new_status)
            return self._json_response(data=service.serialize_delivery(delivery))
        except Exception as exc:
            _logger.exception('Update status failed')
            return self._json_response(error=str(exc), status=500)

    @http.route(
        '/api/delivery/<int:delivery_id>/complete',
        type='http', auth='public', methods=['POST'], csrf=False
    )
    def complete_delivery(self, delivery_id, **kwargs):
        """Complete delivery with confirmation PIN and proof of delivery."""
        body = self._parse_json_body()
        service = self._get_delivery_service()
        delivery = request.env['smart.delivery.order'].sudo().browse(delivery_id)
        if not delivery.exists():
            return self._json_response(error='Delivery not found', status=404)

        try:
            service.complete_delivery(
                delivery,
                pin=body.get('pin'),
                pod_image=body.get('pod_image'),
                pod_signature=body.get('pod_signature'),
            )
            return self._json_response(data=service.serialize_delivery(delivery))
        except ValueError as exc:
            return self._json_response(error=str(exc), status=400)
        except Exception as exc:
            _logger.exception('Complete delivery failed')
            return self._json_response(error=str(exc), status=500)

    @http.route(
        '/api/delivery/<int:delivery_id>/rate',
        type='http', auth='public', methods=['POST'], csrf=False
    )
    def rate_delivery(self, delivery_id, **kwargs):
        """Submit customer rating and feedback for a delivered order."""
        body = self._parse_json_body()
        rating = body.get('rating')
        if rating is None:
            return self._json_response(error='rating field required', status=400)

        service = self._get_delivery_service()
        delivery = request.env['smart.delivery.order'].sudo().browse(delivery_id)
        if not delivery.exists():
            return self._json_response(error='Delivery not found', status=404)

        try:
            service.submit_rating(delivery, rating, feedback=body.get('feedback'))
            return self._json_response(data=service.serialize_delivery(delivery))
        except ValueError as exc:
            return self._json_response(error=str(exc), status=400)
        except Exception as exc:
            _logger.exception('Rate delivery failed')
            return self._json_response(error=str(exc), status=500)
