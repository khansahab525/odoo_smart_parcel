"""Base controller utilities for JSON API responses.

Stateless API — no Odoo sessions. All ORM access via sudo().
"""

import json
import logging

from odoo import http
from odoo.exceptions import AccessDenied
from odoo.http import request

_logger = logging.getLogger(__name__)


class ApiBaseController(http.Controller):
    """Mixin-style base for stateless API controllers."""

    def _json_response(self, data=None, status=200, error=None):
        body = {'success': status < 400}
        if error:
            body['error'] = error
        if data is not None:
            body['data'] = data
        return request.make_response(
            json.dumps(body, default=str),
            headers=[('Content-Type', 'application/json')],
            status=status,
        )

    def _parse_json_body(self):
        try:
            return json.loads(request.httprequest.get_data(as_text=True) or '{}')
        except (json.JSONDecodeError, TypeError):
            return {}

    def _resolve_database(self, body=None):
        """Resolve target database from body, query param, or config."""
        body = body or {}
        db = (
            body.get('db')
            or request.httprequest.args.get('db')
            or request.db
        )
        if not db:
            db = request.env['ir.config_parameter'].sudo().get_param(
                'smart_delivery.default_db', 'smart_delivery'
            )
        return db

    def _get_delivery_service(self):
        from ..services.delivery_service import DeliveryService
        return DeliveryService(request.env)

    def _verify_credentials(self, login, password, db=None):
        """Verify login/password via ORM without creating a session.

        Odoo 17 signature: _check_credentials(password: str, env: dict)
        Uses res.users.authenticate() which validates credentials only.
        """
        db = db or self._resolve_database()
        try:
            uid = request.env['res.users'].authenticate(
                db, login, password, {'interactive': False},
            )
        except AccessDenied:
            raise AccessDenied('Invalid credentials') from None

        if not uid:
            raise AccessDenied('Invalid credentials')

        user = request.env['res.users'].sudo().browse(uid)
        if not user.exists():
            raise AccessDenied('Invalid credentials')
        return user

    def _get_user_by_id(self, user_id):
        """Fetch a user record by ID using sudo."""
        if not user_id:
            return None
        user = request.env['res.users'].sudo().browse(int(user_id))
        return user if user.exists() else None

    def _serialize_user(self, user, db=None):
        """Serialize user for API login response."""
        return {
            'user_id': user.id,
            'name': user.name,
            'login': user.login,
            'role': user.smart_delivery_role or 'customer',
            'db': db,
            'driver_id': user.smart_driver_id.id if user.smart_driver_id else None,
        }
