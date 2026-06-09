"""Firebase Cloud Messaging integration for push notifications."""

import json
import logging

import requests

_logger = logging.getLogger(__name__)

FCM_LEGACY_URL = 'https://fcm.googleapis.com/fcm/send'


def _get_fcm_server_key(env):
    return env['ir.config_parameter'].sudo().get_param(
        'smart_delivery.fcm_server_key', ''
    )


def send_fcm_notification(env, tokens, title, body, data=None):
    """Send push notification to one or more FCM device tokens."""
    server_key = _get_fcm_server_key(env)
    if not server_key or not tokens:
        return False

    if isinstance(tokens, str):
        tokens = [tokens]

    headers = {
        'Authorization': f'key={server_key}',
        'Content-Type': 'application/json',
    }
    payload = {
        'registration_ids': tokens,
        'notification': {
            'title': title,
            'body': body,
            'sound': 'default',
        },
        'data': data or {},
        'priority': 'high',
    }

    try:
        response = requests.post(
            FCM_LEGACY_URL, headers=headers,
            json=payload, timeout=15,
        )
        response.raise_for_status()
        result = response.json()
        _logger.info('FCM sent: success=%s', result.get('success', 0))
        return result.get('success', 0) > 0
    except Exception as exc:
        _logger.warning('FCM send failed: %s', exc)
        return False


def send_to_user(env, user_id, title, body, data=None):
    """Send FCM notification to all active tokens for a user."""
    Token = env['smart.fcm.token'].sudo()
    tokens = Token.search([
        ('user_id', '=', user_id),
        ('is_active', '=', True),
    ]).mapped('token')

    if not tokens:
        return False
    return send_fcm_notification(env, tokens, title, body, data)
