"""Business logic service layer for smart delivery operations.

Controllers should delegate to this service — never duplicate logic.
"""

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
        vals = {
            'customer_name': data.get('customer_name'),
            'customer_phone': data.get('customer_phone'),
            'pickup_lat': data.get('pickup_lat'),
            'pickup_lng': data.get('pickup_lng'),
            'delivery_lat': data.get('delivery_lat'),
            'delivery_lng': data.get('delivery_lng'),
            'pickup_address': data.get('pickup_address'),
            'delivery_address': data.get('delivery_address'),
            'current_lat': data.get('pickup_lat'),
            'current_lng': data.get('pickup_lng'),
            'customer_user_id': data.get('customer_user_id'),
        }
        if data.get('driver_id'):
            vals['driver_id'] = data['driver_id']
            vals['status'] = 'assigned'

        return Delivery.create(vals)

    def assign_driver(self, delivery, driver_id):
        """Assign a driver to a delivery."""
        delivery.write({
            'driver_id': driver_id,
            'status': 'assigned',
        })
        self._send_notification(delivery, 'assigned')
        return delivery

    def update_status(self, delivery, new_status):
        """Update delivery status and trigger notifications."""
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

        now = fields.Datetime.now()

        driver.write({'current_lat': latitude, 'current_lng': longitude})

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

    def serialize_delivery(self, delivery):
        """Serialize delivery record to API-friendly dict."""
        driver = delivery.driver_id
        return {
            'id': delivery.id,
            'name': delivery.name or '',
            'customer_name': delivery.customer_name or '',
            'customer_phone': delivery.customer_phone or '',
            'status': delivery.status or 'created',
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
                'current_lat': self._optional_float(driver.current_lat),
                'current_lng': self._optional_float(driver.current_lng),
            } if driver else None,
            'pickup_address': delivery.pickup_address or '',
            'delivery_address': delivery.delivery_address or '',
            'confirmation_pin': delivery.confirmation_pin or '',
            'has_pod': bool(delivery.pod_image or delivery.pod_signature),
            'rating': delivery.rating or None,
            'feedback': delivery.feedback or '',
        }

    def serialize_driver(self, driver):
        """Serialize driver record to API-friendly dict."""
        return {
            'id': driver.id,
            'name': driver.name,
            'phone': driver.phone,
            'is_active': driver.is_active,
            'current_lat': driver.current_lat,
            'current_lng': driver.current_lng,
            'active_delivery_count': driver.active_delivery_count,
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
