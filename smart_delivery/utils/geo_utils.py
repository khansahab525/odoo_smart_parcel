"""Geographic utility functions for distance and ETA calculations."""

import math
from datetime import datetime, timedelta

EARTH_RADIUS_KM = 6371.0
BASE_SPEED_KMH = 40.0

TRAFFIC_MULTIPLIERS = {
    'low': 1.0,
    'medium': 1.3,
    'high': 1.6,
}


def haversine_distance(lat1, lng1, lat2, lng2):
    """Calculate distance in kilometers between two GPS coordinates."""
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lng = math.radians(lng2 - lng1)

    a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lng / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return EARTH_RADIUS_KM * c


def calculate_eta_minutes(distance_km, traffic_level='medium'):
    """Calculate ETA in minutes using rule-based speed assumptions."""
    multiplier = TRAFFIC_MULTIPLIERS.get(traffic_level, 1.3)
    adjusted_speed = BASE_SPEED_KMH / multiplier
    if adjusted_speed <= 0:
        return 0
    hours = distance_km / adjusted_speed
    return max(1, int(round(hours * 60)))


def calculate_eta_datetime(eta_minutes, base_time=None):
    """Return ETA as datetime from base time (defaults to now)."""
    base = base_time or datetime.now()
    return base + timedelta(minutes=eta_minutes)


def determine_traffic_level(speed_kmh):
    """Infer traffic level from current speed (rule-based)."""
    if speed_kmh is None:
        return 'medium'
    if speed_kmh >= 30:
        return 'low'
    if speed_kmh >= 10:
        return 'medium'
    return 'high'
