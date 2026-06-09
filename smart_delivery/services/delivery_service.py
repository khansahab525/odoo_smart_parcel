"""Business logic service layer for smart delivery operations.

All rule-based ETA, delay detection, and risk scoring lives here.
Controllers should delegate to this service — never duplicate logic.
"""

from datetime import datetime, timedelta

from odoo import fields

from ..utils.geo_utils import (
    calculate_eta_datetime,
    calculate_eta_minutes,
    determine_traffic_level,
    haversine_distance,
)
from ..utils.event_utils import broadcast_event
from ..utils.fcm_utils import send_to_user
from ..utils.openai_utils import generate_chat_response, generate_notification


class DeliveryService:
    """Service class for delivery business logic."""

    IDLE_THRESHOLD_MINUTES = 12
    LOW_SPEED_THRESHOLD_KMH = 10
    ETA_INCREASE_THRESHOLD = 0.30
    ROUTE_DEVIATION_THRESHOLD_KM = 2.0

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
            'current_lat': data.get('pickup_lat'),
            'current_lng': data.get('pickup_lng'),
            'customer_user_id': data.get('customer_user_id'),
        }
        if data.get('driver_id'):
            vals['driver_id'] = data['driver_id']
            vals['status'] = 'assigned'

        delivery = Delivery.create(vals)
        self._recalculate_metrics(delivery)
        delivery.write({'initial_eta_minutes': delivery.eta_minutes})
        return delivery

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

        self._recalculate_metrics(delivery)

        if delivery.delay_status in ('delayed', 'high_risk'):
            self._send_notification(delivery, 'delayed')

        self._broadcast_tracking_event(delivery, 'location_update')
        return delivery

    # ------------------------------------------------------------------
    # ETA calculation (rule-based)
    # ------------------------------------------------------------------

    def calculate_eta(self, delivery):
        """Calculate ETA using Haversine distance and rule-based speed."""
        if not delivery.current_lat or not delivery.current_lng:
            lat = delivery.pickup_lat
            lng = delivery.pickup_lng
        else:
            lat = delivery.current_lat
            lng = delivery.current_lng

        distance = haversine_distance(
            lat, lng, delivery.delivery_lat, delivery.delivery_lng
        )
        traffic = delivery.traffic_level or determine_traffic_level(delivery.last_speed)
        eta_minutes = calculate_eta_minutes(distance, traffic)
        eta_dt = calculate_eta_datetime(eta_minutes)

        return {
            'eta_minutes': eta_minutes,
            'eta_datetime': eta_dt,
            'distance_km': round(distance, 2),
            'traffic_level': traffic,
        }

    # ------------------------------------------------------------------
    # Delay detection (rule-based)
    # ------------------------------------------------------------------

    def detect_delay(self, delivery):
        """Detect delay status using rule-based heuristics."""
        reasons = []
        status = 'on_time'
        now = fields.Datetime.now()

        if delivery.last_movement_time:
            idle_minutes = (now - delivery.last_movement_time).total_seconds() / 60
            if idle_minutes >= self.IDLE_THRESHOLD_MINUTES:
                reasons.append(f'No movement for {int(idle_minutes)} minutes')
                status = 'delayed'

        if delivery.last_speed is not None and delivery.last_speed < self.LOW_SPEED_THRESHOLD_KMH:
            if delivery.status in ('in_transit', 'out_for_delivery'):
                reasons.append(f'Low speed ({delivery.last_speed:.0f} km/h) — traffic delay')
                status = 'delayed'

        eta_data = self.calculate_eta(delivery)
        if delivery.initial_eta_minutes and delivery.initial_eta_minutes > 0:
            increase = (eta_data['eta_minutes'] - delivery.initial_eta_minutes) / delivery.initial_eta_minutes
            if increase >= self.ETA_INCREASE_THRESHOLD:
                reasons.append(f'ETA increased by {int(increase * 100)}%')
                status = 'high_risk'

        return {
            'delay_status': status,
            'delay_reason': '; '.join(reasons) if reasons else '',
        }

    # ------------------------------------------------------------------
    # Risk scoring (rule-based)
    # ------------------------------------------------------------------

    def calculate_risk_score(self, delivery):
        """Calculate risk score 0-100 based on rule-based factors."""
        score = 0
        now = fields.Datetime.now()

        if delivery.last_movement_time:
            idle_minutes = (now - delivery.last_movement_time).total_seconds() / 60
            if idle_minutes >= 15:
                score += 35
            elif idle_minutes >= 10:
                score += 20
            elif idle_minutes >= 5:
                score += 10

        if delivery.last_speed is not None:
            if delivery.last_speed < 5:
                score += 25
            elif delivery.last_speed < 10:
                score += 15
            elif delivery.last_speed < 20:
                score += 5

        deviation = self._calculate_route_deviation(delivery)
        if deviation > self.ROUTE_DEVIATION_THRESHOLD_KM:
            score += 30
        elif deviation > 1.0:
            score += 15

        traffic = delivery.traffic_level or 'medium'
        traffic_scores = {'low': 0, 'medium': 10, 'high': 20}
        score += traffic_scores.get(traffic, 10)

        if delivery.initial_eta_minutes and delivery.initial_eta_minutes > 0:
            eta_data = self.calculate_eta(delivery)
            increase = (eta_data['eta_minutes'] - delivery.initial_eta_minutes) / delivery.initial_eta_minutes
            if increase >= 0.5:
                score += 20
            elif increase >= 0.3:
                score += 10

        score = min(100, max(0, score))

        if score >= 60:
            risk_level = 'high'
        elif score >= 30:
            risk_level = 'medium'
        else:
            risk_level = 'low'

        return {'risk_score': score, 'risk_level': risk_level}

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
            'eta_minutes': self._safe_int(delivery.eta_minutes),
            'eta_datetime': str(delivery.eta_datetime) if delivery.eta_datetime else None,
            'delay_status': delivery.delay_status or 'on_time',
            'delay_reason': delivery.delay_reason or '',
            'risk_score': self._safe_int(delivery.risk_score),
            'risk_level': delivery.risk_level or 'low',
            'traffic_level': delivery.traffic_level or 'medium',
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

    def _recalculate_metrics(self, delivery):
        """Recalculate ETA, delay, and risk for a delivery."""
        eta_data = self.calculate_eta(delivery)
        delay_data = self.detect_delay(delivery)
        risk_data = self.calculate_risk_score(delivery)

        delivery.write({
            'eta_minutes': eta_data['eta_minutes'],
            'eta_datetime': eta_data['eta_datetime'],
            'traffic_level': eta_data['traffic_level'],
            'delay_status': delay_data['delay_status'],
            'delay_reason': delay_data['delay_reason'],
            'risk_score': risk_data['risk_score'],
            'risk_level': risk_data['risk_level'],
        })

    def _detect_movement(self, delivery, new_lat, new_lng):
        """Check if driver has moved significantly (>50 meters)."""
        if not delivery.current_lat or not delivery.current_lng:
            return True
        distance_m = haversine_distance(
            delivery.current_lat, delivery.current_lng, new_lat, new_lng
        ) * 1000
        return distance_m > 50

    def _calculate_route_deviation(self, delivery):
        """Estimate route deviation from direct path (rule-based)."""
        if not delivery.current_lat or not delivery.current_lng:
            return 0.0

        direct = haversine_distance(
            delivery.pickup_lat, delivery.pickup_lng,
            delivery.delivery_lat, delivery.delivery_lng,
        )
        via_current = (
            haversine_distance(
                delivery.pickup_lat, delivery.pickup_lng,
                delivery.current_lat, delivery.current_lng,
            )
            + haversine_distance(
                delivery.current_lat, delivery.current_lng,
                delivery.delivery_lat, delivery.delivery_lng,
            )
        )
        return max(0, via_current - direct)

    def _send_notification(self, delivery, event_type):
        """Generate and log a smart notification."""
        message = self.get_notification(delivery, event_type)
        log_entry = f"[{fields.Datetime.now()}] {event_type}: {message}\n"
        delivery.write({
            'notification_log': (delivery.notification_log or '') + log_entry,
        })

        self._push_fcm(delivery, event_type, message)
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

    def _push_fcm(self, delivery, event_type, message):
        """Send FCM push to customer user if registered."""
        user_id = delivery.customer_user_id.id
        if not user_id:
            return

        titles = {
            'assigned': 'Driver Assigned',
            'picked_up': 'Order Picked Up',
            'in_transit': 'Order In Transit',
            'nearby': 'Driver Nearby',
            'delivered': 'Order Delivered',
            'delayed': 'Delivery Delay',
        }
        title = titles.get(event_type, 'Delivery Update')
        send_to_user(self.env, user_id, title, message, {
            'delivery_id': str(delivery.id),
            'event_type': event_type,
            'eta_minutes': str(delivery.eta_minutes or 0),
        })
