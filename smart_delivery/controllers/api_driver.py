import logging

from odoo import http
from odoo.http import request

from .api_base import ApiBaseController

_logger = logging.getLogger(__name__)


class ApiDriverController(ApiBaseController):

    @http.route('/api/driver/create', type='http', auth='public', methods=['POST'], csrf=False)
    def create_driver(self, **kwargs):
        body = self._parse_json_body()
        name = body.get('name')
        if not name:
            return self._json_response(error='name field required', status=400)

        try:
            driver = request.env['smart.driver'].sudo().create({
                'name': name,
                'phone': body.get('phone', ''),
                'is_active': body.get('is_active', True),
                'user_id': body.get('user_id'),
            })
            service = self._get_delivery_service()
            return self._json_response(
                data=service.serialize_driver(driver), status=201
            )
        except Exception as exc:
            _logger.exception('Create driver failed')
            return self._json_response(error=str(exc), status=500)

    @http.route(
        '/api/driver/location/update',
        type='http', auth='public', methods=['POST'], csrf=False
    )
    def update_location(self, **kwargs):
        body = self._parse_json_body()
        required = ['driver_id', 'delivery_id', 'latitude', 'longitude']
        missing = [f for f in required if body.get(f) is None]
        if missing:
            return self._json_response(
                error=f'Missing required fields: {", ".join(missing)}', status=400
            )

        service = self._get_delivery_service()
        try:
            delivery = service.update_driver_location(
                driver_id=int(body['driver_id']),
                delivery_id=int(body['delivery_id']),
                latitude=float(body['latitude']),
                longitude=float(body['longitude']),
                speed=body.get('speed'),
            )
            return self._json_response(data=service.serialize_delivery(delivery))
        except ValueError as exc:
            return self._json_response(error=str(exc), status=404)
        except Exception as exc:
            _logger.exception('Location update failed')
            return self._json_response(error=str(exc), status=500)

    @http.route('/api/driver/<int:driver_id>', type='http', auth='public', methods=['GET'], csrf=False)
    def get_driver(self, driver_id, **kwargs):
        service = self._get_delivery_service()
        driver = request.env['smart.driver'].sudo().browse(driver_id)
        if not driver.exists():
            return self._json_response(error='Driver not found', status=404)
        return self._json_response(data=service.serialize_driver(driver))
