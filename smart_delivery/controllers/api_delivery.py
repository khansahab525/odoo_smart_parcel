import logging
import time

from odoo import http
from odoo.http import request

from .api_base import ApiBaseController

_logger = logging.getLogger(__name__)


class ApiDeliveryController(ApiBaseController):

    def _delivery_domain_for_user(self, user_id):
        if not user_id:
            return []
        user = self._get_user_by_id(user_id)
        if not user:
            raise ValueError('User not found')

        role = user.smart_delivery_role or 'customer'
        is_admin = role == 'admin' or user.has_group('base.group_system')
        if is_admin:
            return []
        if role == 'driver':
            return (
                [('driver_id', '=', user.smart_driver_id.id)]
                if user.smart_driver_id else [('id', '=', 0)]
            )
        if role == 'customer':
            if user.smart_customer_phone:
                return [
                    '|',
                    ('customer_user_id', '=', user.id),
                    ('customer_phone', '=', user.smart_customer_phone),
                ]
            return [('customer_user_id', '=', user.id)]
        return []

    @staticmethod
    def _delivery_state_signature(deliveries):
        return ','.join(
            f'{delivery.id}:{delivery.status}:'
            f'{delivery.driver_id.id if delivery.driver_id else 0}'
            for delivery in deliveries
        )

    def _validate_driver_access(self, body, delivery):
        user = self._get_user_by_id(body.get('user_id'))
        if (
            not user
            or user.smart_delivery_role != 'driver'
            or not user.smart_driver_id
            or delivery.driver_id != user.smart_driver_id
        ):
            raise ValueError('This delivery is not assigned to this driver')

    def _validate_customer_access(self, body, delivery):
        user = self._get_user_by_id(body.get('user_id'))
        owns_delivery = user and (
            delivery.customer_user_id == user
            or (
                not delivery.customer_user_id
                and user.smart_customer_phone
                and delivery.customer_phone == user.smart_customer_phone
            )
        )
        if (
            not user
            or user.smart_delivery_role != 'customer'
            or not owns_delivery
        ):
            raise ValueError('This order does not belong to this customer')

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
            return self._json_response(
                data=service.serialize_delivery(delivery), status=201
            )
        except ValueError as exc:
            return self._json_response(error=str(exc), status=400)
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
        service.expire_pending_offers()
        user_id = kwargs.get('user_id')
        try:
            domain = self._delivery_domain_for_user(user_id)
        except ValueError as exc:
            return self._json_response(error=str(exc), status=404)

        status_filter = kwargs.get('status')
        if status_filter:
            domain.append(('status', '=', status_filter))

        deliveries = request.env['smart.delivery.order'].sudo().search(domain)
        return self._json_response(data=[
            service.serialize_delivery(d) for d in deliveries
        ])

    @http.route(
        '/api/delivery/list/poll',
        type='http', auth='public', methods=['GET'], csrf=False
    )
    def poll_delivery_list(self, **kwargs):
        """Wait until order status, assignment, or list membership changes."""
        try:
            domain = self._delivery_domain_for_user(kwargs.get('user_id'))
            known_state = kwargs.get('known_state') or ''
            wait_seconds = min(
                max(int(kwargs.get('timeout', 25)), 1),
                30,
            )
            service = self._get_delivery_service()
            start = time.time()

            while time.time() - start < wait_seconds:
                service.expire_pending_offers()
                deliveries = request.env[
                    'smart.delivery.order'
                ].sudo().search(domain)
                state = self._delivery_state_signature(deliveries)
                if state != known_state:
                    return self._json_response(data={
                        'changed': True,
                        'state': state,
                        'deliveries': [
                            service.serialize_delivery(delivery)
                            for delivery in deliveries
                        ],
                    })
                time.sleep(2)

            return self._json_response(data={
                'changed': False,
                'state': known_state,
            })
        except ValueError as exc:
            return self._json_response(error=str(exc), status=400)
        except Exception as exc:
            _logger.exception('Delivery list polling failed')
            return self._json_response(error=str(exc), status=500)

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
            'created', 'finding_driver', 'awaiting_acceptance',
            'assigned', 'picked_up', 'in_transit',
            'out_for_delivery', 'delivered', 'cancelled',
        ]
        if new_status not in valid_statuses:
            return self._json_response(
                error=f'Invalid status. Must be one of: {valid_statuses}', status=400,
            )

        try:
            self._validate_driver_access(body, delivery)
            service.update_status(delivery, new_status)
            return self._json_response(data=service.serialize_delivery(delivery))
        except ValueError as exc:
            return self._json_response(error=str(exc), status=403)
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
            self._validate_driver_access(body, delivery)
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
        '/api/delivery/<int:delivery_id>/cancel',
        type='http', auth='public', methods=['POST'], csrf=False
    )
    def cancel_delivery(self, delivery_id, **kwargs):
        body = self._parse_json_body()
        service = self._get_delivery_service()
        delivery = request.env['smart.delivery.order'].sudo().browse(delivery_id)
        if not delivery.exists():
            return self._json_response(error='Delivery not found', status=404)

        try:
            self._validate_customer_access(body, delivery)
            service.cancel_delivery(delivery)
            return self._json_response(
                data=service.serialize_delivery(delivery)
            )
        except ValueError as exc:
            return self._json_response(error=str(exc), status=400)
        except Exception as exc:
            _logger.exception('Cancel delivery failed')
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
