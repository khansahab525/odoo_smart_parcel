import logging

from odoo import http
from odoo.http import request

from .api_base import ApiBaseController

_logger = logging.getLogger(__name__)


class ApiFcmController(ApiBaseController):

    @http.route('/api/fcm/register', type='http', auth='public', methods=['POST'], csrf=False)
    def register_token(self, **kwargs):
        """Register FCM device token for push notifications."""
        body = self._parse_json_body()
        token = body.get('token', '').strip()
        user_id = body.get('user_id')

        if not token:
            return self._json_response(error='token field required', status=400)
        if not user_id:
            return self._json_response(error='user_id field required', status=400)

        user = self._get_user_by_id(user_id)
        if not user:
            return self._json_response(error='User not found', status=404)

        FcmToken = request.env['smart.fcm.token'].sudo()
        existing = FcmToken.search([
            ('user_id', '=', user.id),
            ('token', '=', token),
        ], limit=1)

        if existing:
            existing.write({
                'is_active': True,
                'device_name': body.get('device_name', existing.device_name),
                'platform': body.get('platform', existing.platform),
            })
            record = existing
        else:
            record = FcmToken.create({
                'user_id': user.id,
                'token': token,
                'device_name': body.get('device_name', ''),
                'platform': body.get('platform', 'android'),
                'is_active': True,
            })

        return self._json_response(data={
            'id': record.id,
            'message': 'FCM token registered successfully',
        })

    @http.route('/api/fcm/unregister', type='http', auth='public', methods=['POST'], csrf=False)
    def unregister_token(self, **kwargs):
        body = self._parse_json_body()
        token = body.get('token', '').strip()
        user_id = body.get('user_id')

        if not token:
            return self._json_response(error='token field required', status=400)
        if not user_id:
            return self._json_response(error='user_id field required', status=400)

        records = request.env['smart.fcm.token'].sudo().search([
            ('user_id', '=', int(user_id)),
            ('token', '=', token),
        ])
        records.write({'is_active': False})
        return self._json_response(data={'message': 'FCM token unregistered'})
