"""OpenAI integration for chatbot responses and smart notifications."""

import json
import logging

import requests

_logger = logging.getLogger(__name__)

OPENAI_API_URL = 'https://api.openai.com/v1/chat/completions'
DEFAULT_MODEL = 'gpt-4o-mini'


def _get_api_key(env):
    return env['ir.config_parameter'].sudo().get_param('smart_delivery.openai_api_key', '')


def _call_openai(env, system_prompt, user_prompt, max_tokens=300):
    """Make a chat completion request to OpenAI API."""
    api_key = _get_api_key(env)
    if not api_key:
        return None

    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json',
    }
    payload = {
        'model': DEFAULT_MODEL,
        'messages': [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': user_prompt},
        ],
        'max_tokens': max_tokens,
        'temperature': 0.7,
    }

    try:
        response = requests.post(OPENAI_API_URL, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        data = response.json()
        return data['choices'][0]['message']['content'].strip()
    except Exception as exc:
        _logger.warning('OpenAI API call failed: %s', exc)
        return None


def generate_chat_response(env, delivery_data, user_message):
    """Generate a human-readable chat response about delivery status."""
    system_prompt = (
        'You are a helpful delivery assistant for a last-mile delivery service. '
        'Answer customer questions about their order using ONLY the provided delivery data. '
        'Be concise, friendly, and accurate. Do not invent information.'
    )
    user_prompt = (
        f"Customer question: {user_message}\n\n"
        f"Delivery data (JSON):\n{json.dumps(delivery_data, indent=2, default=str)}"
    )

    result = _call_openai(env, system_prompt, user_prompt)
    if result:
        return result

    return _fallback_chat_response(delivery_data)


def generate_notification(env, event_type, delivery_data):
    """Generate a smart notification message for delivery events."""
    system_prompt = (
        'You are a notification writer for a delivery app. '
        'Write a short, friendly push notification (max 2 sentences) '
        'based on the event and delivery data provided.'
    )
    user_prompt = (
        f"Event: {event_type}\n\n"
        f"Delivery data (JSON):\n{json.dumps(delivery_data, indent=2, default=str)}"
    )

    result = _call_openai(env, system_prompt, user_prompt, max_tokens=100)
    if result:
        return result

    return _fallback_notification(event_type, delivery_data)


def _fallback_chat_response(delivery_data):
    """Rule-based fallback when OpenAI is unavailable."""
    eta = delivery_data.get('eta_minutes', 'unknown')
    status = delivery_data.get('status', 'unknown')
    delay = delivery_data.get('delay_status', 'on_time')

    if delay == 'high_risk':
        return (
            f"Your order is currently {status}. "
            f"Estimated arrival is in about {eta} minutes, "
            f"but there may be significant delays."
        )
    if delay == 'delayed':
        return (
            f"Your order is {status} and will arrive in approximately {eta} minutes. "
            f"There is a slight delay."
        )
    return (
        f"Your order is {status} and on track to arrive in about {eta} minutes."
    )


def _fallback_notification(event_type, delivery_data):
    """Rule-based fallback notifications."""
    fallbacks = {
        'picked_up': 'Your driver has picked up your order and is on the way!',
        'in_transit': f"Your delivery is in transit. ETA: {delivery_data.get('eta_minutes', '?')} minutes.",
        'nearby': 'Your delivery is approximately 10 minutes away!',
        'delayed': 'Possible delay due to traffic conditions. We apologize for the inconvenience.',
        'delivered': 'Your order has been delivered. Thank you for your patience!',
        'assigned': 'A driver has been assigned to your delivery.',
    }
    return fallbacks.get(event_type, f"Delivery update: {event_type}")
