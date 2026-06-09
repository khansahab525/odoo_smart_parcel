import logging

from odoo import http
from odoo.http import request

from .api_base import ApiBaseController

_logger = logging.getLogger(__name__)


class ApiTrackingController(ApiBaseController):

    @http.route(
        '/api/tracking/<int:delivery_id>',
        type='http', auth='public', methods=['GET'], csrf=False
    )
    def track_delivery(self, delivery_id, **kwargs):
        """Return live tracking data for customer map view."""
        service = self._get_delivery_service()
        delivery = request.env['smart.delivery.order'].sudo().browse(delivery_id)
        if not delivery.exists():
            return self._json_response(error='Delivery not found', status=404)

        driver = delivery.driver_id
        gps_logs = request.env['smart.gps.log'].sudo().search(
            [('delivery_id', '=', delivery_id)],
            order='timestamp desc',
            limit=20,
        )

        driver_lat = (
            service._optional_float(driver.current_lat) if driver
            else service._optional_float(delivery.current_lat)
        )
        driver_lng = (
            service._optional_float(driver.current_lng) if driver
            else service._optional_float(delivery.current_lng)
        )

        tracking_data = {
            'delivery': service.serialize_delivery(delivery),
            'driver_location': {
                'latitude': driver_lat,
                'longitude': driver_lng,
            },
            'destination': {
                'latitude': service._safe_float(delivery.delivery_lat),
                'longitude': service._safe_float(delivery.delivery_lng),
            },
            'pickup': {
                'latitude': service._safe_float(delivery.pickup_lat),
                'longitude': service._safe_float(delivery.pickup_lng),
            },
            'route_history': [
                {
                    'latitude': service._safe_float(log.latitude),
                    'longitude': service._safe_float(log.longitude),
                    'speed': service._optional_float(log.speed),
                    'timestamp': str(log.timestamp),
                }
                for log in gps_logs
            ],
            'notifications': [
                n for n in (delivery.notification_log or '').strip().split('\n')[-5:]
                if n
            ],
        }
        return self._json_response(data=tracking_data)
