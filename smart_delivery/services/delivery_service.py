"""Business logic service layer for smart delivery operations.

Controllers should delegate to this service — never duplicate logic.
"""

from datetime import datetime, timedelta, timezone

from odoo import fields

from ..utils.geo_utils import haversine_distance
from ..utils.event_utils import broadcast_event
from ..utils.openai_utils import generate_chat_response, generate_notification


class DeliveryService:
    """Service class for delivery business logic."""

    def __init__(self, env):
        self.env = env

    # ------------------------------------------------------------------
    # Order lifecycle
    # ------------------------------------------------------------------

    def create_delivery(self, data):
        """Create a new delivery order."""
        Delivery = self.env['smart.delivery.order'].sudo()
        parcel_size = data.get('parcel_size') or 'small'
        valid_sizes = {'document', 'small', 'medium', 'large'}
        if parcel_size not in valid_sizes:
            raise ValueError(
                f'Invalid parcel_size. Must be one of: {sorted(valid_sizes)}'
            )

        weight_kg = self._required_float(
            data.get('parcel_weight_kg', 1.0), 'parcel_weight_kg'
        )
        if weight_kg <= 0 or weight_kg > 100:
            raise ValueError(
                'parcel_weight_kg must be greater than 0 and no more than 100'
            )

        pickup_lat = self._required_float(data.get('pickup_lat'), 'pickup_lat')
        pickup_lng = self._required_float(data.get('pickup_lng'), 'pickup_lng')
        delivery_lat = self._required_float(
            data.get('delivery_lat'), 'delivery_lat'
        )
        delivery_lng = self._required_float(
            data.get('delivery_lng'), 'delivery_lng'
        )
        is_fragile = data.get('is_fragile') is True
        distance_km = haversine_distance(
            pickup_lat, pickup_lng, delivery_lat, delivery_lng
        )
        estimated_price = self._calculate_estimated_price(
            distance_km, parcel_size, weight_kg, is_fragile
        )
        scheduled_at = self._parse_scheduled_at(data.get('scheduled_at'))

        vals = {
            'customer_name': data.get('customer_name'),
            'customer_phone': data.get('customer_phone'),
            'pickup_lat': pickup_lat,
            'pickup_lng': pickup_lng,
            'delivery_lat': delivery_lat,
            'delivery_lng': delivery_lng,
            'pickup_address': data.get('pickup_address'),
            'delivery_address': data.get('delivery_address'),
            'current_lat': pickup_lat,
            'current_lng': pickup_lng,
            'customer_user_id': data.get('customer_user_id'),
            'parcel_size': parcel_size,
            'parcel_weight_kg': weight_kg,
            'parcel_description': (data.get('parcel_description') or '').strip(),
            'is_fragile': is_fragile,
            'delivery_notes': (data.get('delivery_notes') or '').strip(),
            'scheduled_at': scheduled_at,
            'estimated_distance_km': round(distance_km, 2),
            'estimated_price': estimated_price,
        }
        delivery = Delivery.create(vals)

        if data.get('driver_id'):
            driver = self.env['smart.driver'].sudo().browse(
                int(data['driver_id'])
            )
            self.force_assign_driver(delivery, driver)
        elif data.get('preferred_driver_id'):
            driver = self.env['smart.driver'].sudo().browse(
                int(data['preferred_driver_id'])
            )
            self.offer_driver(delivery, driver, source='preferred')
        else:
            self.broadcast_to_nearby_drivers(delivery)

        return delivery

    def _required_float(self, value, field_name):
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f'{field_name} must be a number') from exc

    def _parse_scheduled_at(self, value):
        if not value:
            return False
        try:
            parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        except ValueError as exc:
            raise ValueError('scheduled_at must be a valid ISO-8601 date') from exc

        if parsed.tzinfo:
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        if parsed <= fields.Datetime.now():
            raise ValueError('scheduled_at must be in the future')
        return parsed

    def _calculate_estimated_price(
        self, distance_km, parcel_size, weight_kg, is_fragile
    ):
        size_surcharges = {
            'document': 0.0,
            'small': 1.5,
            'medium': 3.0,
            'large': 6.0,
        }
        extra_weight_fee = max(0.0, weight_kg - 2.0) * 0.45
        fragile_fee = 2.0 if is_fragile else 0.0
        price = (
            4.5
            + (distance_km * 1.2)
            + size_surcharges[parcel_size]
            + extra_weight_fee
            + fragile_fee
        )
        return round(price, 2)

    def get_available_drivers(
        self, search=None, pickup_lat=None, pickup_lng=None
    ):
        online_cutoff = fields.Datetime.now() - timedelta(minutes=2)
        domain = [
            ('is_active', '=', True),
            ('is_online', '=', True),
            ('last_location_time', '>=', online_cutoff),
        ]
        if search:
            domain.append(('name', 'ilike', search.strip()))

        drivers = self.env['smart.driver'].sudo().search(
            domain, order='name asc', limit=30
        )
        drivers = drivers.sorted(
            key=lambda driver: (driver.active_delivery_count, driver.name or '')
        )
        drivers = drivers.filtered(
            lambda driver: driver.active_delivery_count == 0
        )
        result = []
        for driver in drivers:
            distance_km = None
            if (
                pickup_lat is not None
                and pickup_lng is not None
                and driver.current_lat
                and driver.current_lng
            ):
                distance_km = haversine_distance(
                    float(pickup_lat),
                    float(pickup_lng),
                    driver.current_lat,
                    driver.current_lng,
                )
            result.append(self.serialize_driver(driver, distance_km=distance_km))
        return result

    def offer_driver(self, delivery, driver, source='admin', distance_km=None):
        if not driver.exists() or not driver.is_active:
            raise ValueError('Selected driver is not active')
        if delivery.driver_id or delivery.status not in (
            'created', 'finding_driver', 'awaiting_acceptance'
        ):
            raise ValueError('This delivery can no longer receive driver offers')
        if distance_km is None and driver.current_lat and driver.current_lng:
            distance_km = haversine_distance(
                delivery.pickup_lat,
                delivery.pickup_lng,
                driver.current_lat,
                driver.current_lng,
            )

        Offer = self.env['smart.delivery.offer'].sudo()
        if source in ('preferred', 'admin'):
            delivery.offer_ids.filtered(
                lambda item: item.status == 'pending'
            ).write({
                'status': 'cancelled',
                'responded_at': fields.Datetime.now(),
            })

        now = fields.Datetime.now()
        expires_at = now + timedelta(seconds=60)
        vals = {
            'source': source,
            'status': 'pending',
            'distance_km': distance_km or 0.0,
            'offered_at': now,
            'expires_at': expires_at,
            'responded_at': False,
        }
        offer = Offer.create({
            **vals,
            'delivery_id': delivery.id,
            'driver_id': driver.id,
        })

        delivery.write({
            'status': 'awaiting_acceptance',
            'requested_driver_id': (
                driver.id if source in ('preferred', 'admin') else False
            ),
            'assignment_method': source,
        })
        return offer

    def broadcast_to_nearby_drivers(self, delivery, radius_km=1.0):
        if delivery.driver_id:
            raise ValueError('This delivery already has a driver')

        delivery.offer_ids.filtered(
            lambda item: item.status == 'pending'
        ).write({
            'status': 'cancelled',
            'responded_at': fields.Datetime.now(),
        })

        online_cutoff = fields.Datetime.now() - timedelta(minutes=2)
        drivers = self.env['smart.driver'].sudo().search([
            ('is_active', '=', True),
            ('is_online', '=', True),
            ('last_location_time', '>=', online_cutoff),
            ('current_lat', '!=', 0),
            ('current_lng', '!=', 0),
        ])
        offers = self.env['smart.delivery.offer'].sudo()
        for driver in drivers:
            if driver.active_delivery_count:
                continue
            distance_km = haversine_distance(
                delivery.pickup_lat,
                delivery.pickup_lng,
                driver.current_lat,
                driver.current_lng,
            )
            if distance_km <= radius_km:
                offers |= self.offer_driver(
                    delivery,
                    driver,
                    source='nearby',
                    distance_km=distance_km,
                )

        if not offers:
            delivery.write({
                'status': 'finding_driver',
                'assignment_method': 'nearby',
                'requested_driver_id': False,
            })
        return offers

    def expire_pending_offers(self):
        now = fields.Datetime.now()
        Offer = self.env['smart.delivery.offer'].sudo()
        expired = Offer.search([
            ('status', '=', 'pending'),
            ('expires_at', '<=', now),
        ])
        deliveries = expired.mapped('delivery_id')
        if expired:
            expired.write({'status': 'expired', 'responded_at': now})
        for delivery in deliveries.filtered(lambda order: not order.driver_id):
            if not delivery.offer_ids.filtered(
                lambda item: item.status == 'pending'
            ):
                delivery.write({'status': 'finding_driver'})
        return expired

    def get_driver_offers(self, driver):
        self.expire_pending_offers()
        return self.env['smart.delivery.offer'].sudo().search([
            ('driver_id', '=', driver.id),
            ('status', '=', 'pending'),
            ('expires_at', '>', fields.Datetime.now()),
        ], order='offered_at desc')

    def accept_offer(self, offer, driver):
        self.expire_pending_offers()
        self.env.cr.execute(
            'SELECT id FROM smart_driver WHERE id = %s FOR UPDATE',
            [driver.id],
        )
        self.env.cr.execute(
            'SELECT id FROM smart_delivery_order WHERE id = %s FOR UPDATE',
            [offer.delivery_id.id],
        )
        offer.invalidate_recordset()
        delivery = offer.delivery_id
        delivery.invalidate_recordset(['driver_id', 'status'])

        if offer.driver_id != driver:
            raise ValueError('This offer does not belong to this driver')
        if offer.status != 'pending' or offer.expires_at <= fields.Datetime.now():
            raise ValueError('This delivery offer has expired')
        if delivery.driver_id or delivery.status not in (
            'created', 'finding_driver', 'awaiting_acceptance'
        ):
            raise ValueError('This delivery has already been assigned')
        active_delivery_count = self.env['smart.delivery.order'].sudo().search_count([
            ('driver_id', '=', driver.id),
            ('status', 'in', (
                'assigned',
                'picked_up',
                'in_transit',
                'out_for_delivery',
            )),
        ])
        if active_delivery_count:
            raise ValueError(
                'Complete the current delivery before accepting another one'
            )

        now = fields.Datetime.now()
        offer.write({'status': 'accepted', 'responded_at': now})
        delivery.offer_ids.filtered(
            lambda item: item.id != offer.id and item.status == 'pending'
        ).write({'status': 'cancelled', 'responded_at': now})
        other_driver_offers = self.env['smart.delivery.offer'].sudo().search([
            ('driver_id', '=', driver.id),
            ('id', '!=', offer.id),
            ('status', '=', 'pending'),
        ])
        affected_deliveries = other_driver_offers.mapped('delivery_id')
        if other_driver_offers:
            other_driver_offers.write({
                'status': 'cancelled',
                'responded_at': now,
            })
        for affected_delivery in affected_deliveries.filtered(
            lambda order: not order.driver_id
        ):
            if not affected_delivery.offer_ids.filtered(
                lambda item: item.status == 'pending'
            ):
                affected_delivery.write({'status': 'finding_driver'})
        delivery.write({
            'driver_id': driver.id,
            'status': 'assigned',
            'requested_driver_id': False,
            'assignment_method': offer.source,
            'assignment_accepted_at': now,
        })
        self._send_notification(delivery, 'assigned')
        self._broadcast_tracking_event(delivery, 'status_change')
        return delivery

    def reject_offer(self, offer, driver):
        self.expire_pending_offers()
        if offer.driver_id != driver:
            raise ValueError('This offer does not belong to this driver')
        if offer.status != 'pending':
            raise ValueError('This offer is no longer pending')

        offer.write({
            'status': 'rejected',
            'responded_at': fields.Datetime.now(),
        })
        delivery = offer.delivery_id
        if (
            not delivery.driver_id
            and not delivery.offer_ids.filtered(
                lambda item: item.status == 'pending'
            )
        ):
            delivery.write({'status': 'finding_driver'})
        return delivery

    def force_assign_driver(self, delivery, driver):
        if not driver.exists() or not driver.is_active:
            raise ValueError('Selected driver is not active')
        now = fields.Datetime.now()
        delivery.offer_ids.filtered(
            lambda item: item.status == 'pending'
        ).write({'status': 'cancelled', 'responded_at': now})
        delivery.write({
            'driver_id': driver.id,
            'status': 'assigned',
            'requested_driver_id': False,
            'assignment_method': 'forced',
            'assignment_accepted_at': now,
        })
        self._send_notification(delivery, 'assigned')
        self._broadcast_tracking_event(delivery, 'status_change')
        return delivery

    def assign_driver(self, delivery, driver_id):
        """Backward-compatible forced assignment."""
        driver = self.env['smart.driver'].sudo().browse(int(driver_id))
        return self.force_assign_driver(delivery, driver)

    def cancel_delivery(self, delivery):
        """Allow cancellation only before the driver starts the trip."""
        self.env.cr.execute(
            'SELECT id FROM smart_delivery_order WHERE id = %s FOR UPDATE',
            [delivery.id],
        )
        delivery.invalidate_recordset(['status'])
        cancellable_statuses = {
            'created',
            'finding_driver',
            'awaiting_acceptance',
            'assigned',
        }
        if delivery.status not in cancellable_statuses:
            raise ValueError(
                'This order cannot be cancelled after the trip has started'
            )

        now = fields.Datetime.now()
        delivery.offer_ids.filtered(
            lambda item: item.status == 'pending'
        ).write({
            'status': 'cancelled',
            'responded_at': now,
        })
        delivery.write({'status': 'cancelled'})
        self._send_notification(delivery, 'cancelled')
        self._broadcast_tracking_event(delivery, 'status_change')
        return delivery

    def update_status(self, delivery, new_status):
        """Update delivery status and trigger notifications."""
        self.env.cr.execute(
            'SELECT id FROM smart_delivery_order WHERE id = %s FOR UPDATE',
            [delivery.id],
        )
        delivery.invalidate_recordset(['status'])
        if delivery.status in ('cancelled', 'delivered'):
            raise ValueError(
                f'Delivery is already {delivery.status.replace("_", " ")}'
            )
        old_status = delivery.status
        delivery.write({'status': new_status})

        event_map = {
            'picked_up': 'picked_up',
            'in_transit': 'in_transit',
            'out_for_delivery': 'nearby',
            'delivered': 'delivered',
        }
        if new_status in event_map and new_status != old_status:
            self._send_notification(delivery, event_map[new_status])

        self._broadcast_tracking_event(delivery, 'status_change')
        return delivery

    def complete_delivery(self, delivery, pin=None, pod_image=None, pod_signature=None):
        """Complete a delivery with PIN verification and proof of delivery."""
        if delivery.status == 'delivered':
            raise ValueError('Delivery is already completed')

        if delivery.confirmation_pin and (pin or '').strip() != delivery.confirmation_pin:
            raise ValueError('Invalid confirmation PIN')

        vals = {'pod_timestamp': fields.Datetime.now()}
        if pod_image:
            vals['pod_image'] = pod_image
        if pod_signature:
            vals['pod_signature'] = pod_signature
        delivery.write(vals)

        return self.update_status(delivery, 'delivered')

    def submit_rating(self, delivery, rating, feedback=None):
        """Store customer rating and feedback for a completed delivery."""
        rating = int(rating)
        if rating < 1 or rating > 5:
            raise ValueError('Rating must be between 1 and 5')
        if delivery.status != 'delivered':
            raise ValueError('Only delivered orders can be rated')

        delivery.write({
            'rating': rating,
            'feedback': (feedback or '').strip(),
        })
        return delivery

    # ------------------------------------------------------------------
    # GPS update flow
    # ------------------------------------------------------------------

    def update_driver_location(self, driver_id, delivery_id, latitude, longitude, speed=None):
        """Process a GPS location update from the driver app."""
        Driver = self.env['smart.driver'].sudo()
        Delivery = self.env['smart.delivery.order'].sudo()
        GpsLog = self.env['smart.gps.log'].sudo()

        driver = Driver.browse(driver_id)
        if not driver.exists():
            raise ValueError('Driver not found')

        delivery = Delivery.browse(delivery_id)
        if not delivery.exists():
            raise ValueError('Delivery not found')
        if delivery.driver_id != driver:
            raise ValueError('This delivery is not assigned to this driver')

        now = fields.Datetime.now()

        driver.write({
            'current_lat': latitude,
            'current_lng': longitude,
            'last_location_time': now,
        })

        movement_detected = self._detect_movement(delivery, latitude, longitude)
        update_vals = {
            'current_lat': latitude,
            'current_lng': longitude,
            'last_speed': speed or 0,
        }
        if movement_detected:
            update_vals['last_movement_time'] = now

        delivery.write(update_vals)

        GpsLog.create({
            'driver_id': driver_id,
            'delivery_id': delivery_id,
            'latitude': latitude,
            'longitude': longitude,
            'speed': speed,
            'timestamp': now,
        })

        self._broadcast_tracking_event(delivery, 'location_update')
        return delivery

    def update_driver_availability_location(
        self, driver, latitude, longitude
    ):
        if not driver.exists() or not driver.is_active:
            raise ValueError('Driver is not active')
        driver.write({
            'current_lat': float(latitude),
            'current_lng': float(longitude),
            'last_location_time': fields.Datetime.now(),
        })
        return driver

    def set_driver_connection(self, driver, connected):
        if connected and not driver.is_active:
            raise ValueError('This driver account is inactive')
        if connected and driver.active_delivery_count:
            raise ValueError(
                'Complete the active delivery before searching for new orders'
            )
        driver.write({'is_online': bool(connected)})
        return driver

    # ------------------------------------------------------------------
    # Chat & notifications (OpenAI)
    # ------------------------------------------------------------------

    def get_chat_response(self, delivery, user_message):
        """Generate AI chat response about a delivery."""
        data = self.serialize_delivery(delivery)
        return generate_chat_response(self.env, data, user_message)

    def get_notification(self, delivery, event_type):
        """Generate AI notification text for a delivery event."""
        data = self.serialize_delivery(delivery)
        return generate_notification(self.env, event_type, data)

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def _safe_int(self, value, default=0):
        """Ensure integers serialize as numbers, never False."""
        if value is None or value is False:
            return default
        return int(value)

    def _safe_float(self, value, default=0.0):
        if value is None or value is False:
            return default
        return float(value)

    def _optional_float(self, value):
        if value is None or value is False:
            return None
        return float(value)

    def _optional_positive_float(self, value):
        number = self._optional_float(value)
        return number if number is not None and number > 0 else None

    def serialize_delivery(self, delivery):
        """Serialize delivery record to API-friendly dict."""
        driver = delivery.driver_id
        pending_offers = delivery.offer_ids.filtered(
            lambda item: item.status == 'pending'
        )
        next_expiry = min(
            pending_offers.mapped('expires_at'),
            default=None,
        )
        return {
            'id': delivery.id,
            'name': delivery.name or '',
            'customer_name': delivery.customer_name or '',
            'customer_phone': delivery.customer_phone or '',
            'status': delivery.status or 'created',
            'assignment_method': delivery.assignment_method or None,
            'pending_offer_count': len(pending_offers),
            'offer_expires_at': (
                f'{next_expiry.isoformat()}Z' if next_expiry else None
            ),
            'pickup_lat': self._safe_float(delivery.pickup_lat),
            'pickup_lng': self._safe_float(delivery.pickup_lng),
            'delivery_lat': self._safe_float(delivery.delivery_lat),
            'delivery_lng': self._safe_float(delivery.delivery_lng),
            'current_lat': self._optional_float(delivery.current_lat),
            'current_lng': self._optional_float(delivery.current_lng),
            'driver': {
                'id': driver.id,
                'name': driver.name or '',
                'phone': driver.phone or '',
                'profile_image': (
                    driver.profile_image.decode()
                    if isinstance(driver.profile_image, bytes)
                    else (driver.profile_image or '')
                ),
                'current_lat': self._optional_float(driver.current_lat),
                'current_lng': self._optional_float(driver.current_lng),
            } if driver else None,
            'pickup_address': delivery.pickup_address or '',
            'delivery_address': delivery.delivery_address or '',
            'parcel_size': delivery.parcel_size or 'small',
            'parcel_weight_kg': self._safe_float(delivery.parcel_weight_kg),
            'parcel_description': delivery.parcel_description or '',
            'is_fragile': bool(delivery.is_fragile),
            'delivery_notes': delivery.delivery_notes or '',
            'scheduled_at': (
                f'{delivery.scheduled_at.isoformat()}Z'
                if delivery.scheduled_at else None
            ),
            'estimated_distance_km': self._optional_positive_float(
                delivery.estimated_distance_km
            ),
            'estimated_price': self._optional_positive_float(
                delivery.estimated_price
            ),
            'currency': delivery.currency_id.name or '',
            'confirmation_pin': delivery.confirmation_pin or '',
            'has_pod': bool(delivery.pod_image or delivery.pod_signature),
            'rating': delivery.rating or None,
            'feedback': delivery.feedback or '',
        }

    def serialize_driver(self, driver, distance_km=None):
        """Serialize driver record to API-friendly dict."""
        return {
            'id': driver.id,
            'name': driver.name,
            'phone': driver.phone,
            'profile_image': (
                driver.profile_image.decode()
                if isinstance(driver.profile_image, bytes)
                else (driver.profile_image or '')
            ),
            'is_active': driver.is_active,
            'is_online': driver.is_online,
            'current_lat': driver.current_lat,
            'current_lng': driver.current_lng,
            'last_location_time': (
                f'{driver.last_location_time.isoformat()}Z'
                if driver.last_location_time else None
            ),
            'distance_km': (
                round(distance_km, 2) if distance_km is not None else None
            ),
            'active_delivery_count': driver.active_delivery_count,
        }

    def serialize_offer(self, offer):
        expires_in_seconds = max(
            0,
            int(
                (offer.expires_at - fields.Datetime.now()).total_seconds()
            ),
        )
        return {
            'id': offer.id,
            'source': offer.source,
            'status': offer.status,
            'distance_km': self._optional_float(offer.distance_km),
            'offered_at': f'{offer.offered_at.isoformat()}Z',
            'expires_at': f'{offer.expires_at.isoformat()}Z',
            'expires_in_seconds': expires_in_seconds,
            'delivery': self.serialize_delivery(offer.delivery_id),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _detect_movement(self, delivery, new_lat, new_lng):
        """Check if driver has moved significantly (>50 meters)."""
        if not delivery.current_lat or not delivery.current_lng:
            return True
        distance_m = haversine_distance(
            delivery.current_lat, delivery.current_lng, new_lat, new_lng
        ) * 1000
        return distance_m > 50

    def _send_notification(self, delivery, event_type):
        """Generate and log a smart notification."""
        message = self.get_notification(delivery, event_type)
        log_entry = f"[{fields.Datetime.now()}] {event_type}: {message}\n"
        delivery.write({
            'notification_log': (delivery.notification_log or '') + log_entry,
        })

        broadcast_event(self.env, delivery, 'notification', {
            'event_type': event_type,
            'message': message,
            'delivery': self.serialize_delivery(delivery),
        })
        return message

    def _broadcast_tracking_event(self, delivery, event_type):
        """Broadcast real-time tracking event for SSE/WebSocket consumers."""
        broadcast_event(self.env, delivery, event_type, {
            'delivery': self.serialize_delivery(delivery),
            'driver_location': {
                'latitude': delivery.current_lat,
                'longitude': delivery.current_lng,
            },
        })
