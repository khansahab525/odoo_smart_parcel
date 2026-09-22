import logging
import time

from odoo import http
from odoo.http import request

from .api_base import ApiBaseController

_logger = logging.getLogger(__name__)


class ApiDriverController(ApiBaseController):

    def _driver_from_user_id(self, user_id):
        user = self._get_user_by_id(user_id)
        if not user or user.smart_delivery_role != 'driver':
            raise ValueError('A valid driver user_id is required')
        if not user.smart_driver_id:
            raise ValueError('No driver profile is linked to this user')
        return user.smart_driver_id.sudo()

    @http.route(
        '/api/drivers/available',
        type='http', auth='public', methods=['GET'], csrf=False
    )
    def available_drivers(self, **kwargs):
        service = self._get_delivery_service()
        try:
            pickup_lat = kwargs.get('pickup_lat')
            pickup_lng = kwargs.get('pickup_lng')
            drivers = service.get_available_drivers(
                search=kwargs.get('search'),
                pickup_lat=(
                    float(pickup_lat) if pickup_lat is not None else None
                ),
                pickup_lng=(
                    float(pickup_lng) if pickup_lng is not None else None
                ),
            )
            return self._json_response(data=drivers)
        except ValueError as exc:
            return self._json_response(error=str(exc), status=400)

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
            authenticated_driver = self._driver_from_user_id(
                body.get('user_id')
            )
            if authenticated_driver.id != int(body['driver_id']):
                raise ValueError('Driver identity does not match user_id')
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

    @http.route(
        '/api/driver/availability/location',
        type='http', auth='public', methods=['POST'], csrf=False
    )
    def update_availability_location(self, **kwargs):
        body = self._parse_json_body()
        try:
            driver = self._driver_from_user_id(body.get('user_id'))
            service = self._get_delivery_service()
            service.update_driver_availability_location(
                driver,
                latitude=float(body.get('latitude')),
                longitude=float(body.get('longitude')),
            )
            return self._json_response(
                data=service.serialize_driver(driver)
            )
        except (TypeError, ValueError) as exc:
            return self._json_response(error=str(exc), status=400)
        except Exception as exc:
            _logger.exception('Driver availability location update failed')
            return self._json_response(error=str(exc), status=500)

    @http.route(
        '/api/driver/availability',
        type='http', auth='public', methods=['POST'], csrf=False
    )
    def set_availability(self, **kwargs):
        body = self._parse_json_body()
        if not isinstance(body.get('connected'), bool):
            return self._json_response(
                error='connected must be true or false', status=400
            )
        try:
            driver = self._driver_from_user_id(body.get('user_id'))
            service = self._get_delivery_service()
            service.set_driver_connection(driver, body['connected'])
            return self._json_response(
                data=service.serialize_driver(driver)
            )
        except ValueError as exc:
            return self._json_response(error=str(exc), status=400)
        except Exception as exc:
            _logger.exception('Driver availability update failed')
            return self._json_response(error=str(exc), status=500)

    @http.route(
        '/api/driver/offers',
        type='http', auth='public', methods=['GET'], csrf=False
    )
    def list_offers(self, **kwargs):
        try:
            driver = self._driver_from_user_id(kwargs.get('user_id'))
            service = self._get_delivery_service()
            offers = service.get_driver_offers(driver)
            return self._json_response(data=[
                service.serialize_offer(offer) for offer in offers
            ])
        except ValueError as exc:
            return self._json_response(error=str(exc), status=400)

    @http.route(
        '/api/driver/offers/poll',
        type='http', auth='public', methods=['GET'], csrf=False
    )
    def poll_offers(self, **kwargs):
        """Wait for the driver's pending offer set to change."""
        try:
            driver = self._driver_from_user_id(kwargs.get('user_id'))
            known_ids = {
                int(value)
                for value in (kwargs.get('known_offer_ids') or '').split(',')
                if value.strip().isdigit()
            }
            wait_seconds = min(
                max(int(kwargs.get('timeout', 25)), 1),
                30,
            )
            service = self._get_delivery_service()
            start = time.time()

            while time.time() - start < wait_seconds:
                offers = service.get_driver_offers(driver)
                current_ids = set(offers.ids)
                if current_ids != known_ids:
                    return self._json_response(data={
                        'changed': True,
                        'offers': [
                            service.serialize_offer(offer)
                            for offer in offers
                        ],
                    })
                time.sleep(1)

            offers = service.get_driver_offers(driver)
            return self._json_response(data={
                'changed': set(offers.ids) != known_ids,
                'offers': [
                    service.serialize_offer(offer) for offer in offers
                ],
            })
        except ValueError as exc:
            return self._json_response(error=str(exc), status=400)
        except Exception as exc:
            _logger.exception('Driver offer polling failed')
            return self._json_response(error=str(exc), status=500)

    @http.route(
        '/api/driver/offers/<int:offer_id>/accept',
        type='http', auth='public', methods=['POST'], csrf=False
    )
    def accept_offer(self, offer_id, **kwargs):
        body = self._parse_json_body()
        try:
            driver = self._driver_from_user_id(body.get('user_id'))
            offer = request.env['smart.delivery.offer'].sudo().browse(offer_id)
            if not offer.exists():
                return self._json_response(error='Offer not found', status=404)
            service = self._get_delivery_service()
            delivery = service.accept_offer(offer, driver)
            return self._json_response(
                data=service.serialize_delivery(delivery)
            )
        except ValueError as exc:
            return self._json_response(error=str(exc), status=409)
        except Exception as exc:
            _logger.exception('Driver offer acceptance failed')
            return self._json_response(error=str(exc), status=500)

    @http.route(
        '/api/driver/offers/<int:offer_id>/reject',
        type='http', auth='public', methods=['POST'], csrf=False
    )
    def reject_offer(self, offer_id, **kwargs):
        body = self._parse_json_body()
        try:
            driver = self._driver_from_user_id(body.get('user_id'))
            offer = request.env['smart.delivery.offer'].sudo().browse(offer_id)
            if not offer.exists():
                return self._json_response(error='Offer not found', status=404)
            service = self._get_delivery_service()
            delivery = service.reject_offer(offer, driver)
            return self._json_response(
                data=service.serialize_delivery(delivery)
            )
        except ValueError as exc:
            return self._json_response(error=str(exc), status=409)
        except Exception as exc:
            _logger.exception('Driver offer rejection failed')
            return self._json_response(error=str(exc), status=500)

    @http.route('/api/driver/<int:driver_id>', type='http', auth='public', methods=['GET'], csrf=False)
    def get_driver(self, driver_id, **kwargs):
        service = self._get_delivery_service()
        driver = request.env['smart.driver'].sudo().browse(driver_id)
        if not driver.exists():
            return self._json_response(error='Driver not found', status=404)
        return self._json_response(data=service.serialize_driver(driver))
