import logging

from odoo import http
from odoo.exceptions import AccessDenied

from .api_base import ApiBaseController

_logger = logging.getLogger(__name__)


class ApiAuthController(ApiBaseController):

    @http.route('/api/auth/login', type='http', auth='public', methods=['POST'], csrf=False)
    def login(self, **kwargs):
        """Verify credentials via sudo ORM — no session created."""
        body = self._parse_json_body()
        login = body.get('login') or body.get('email')
        password = body.get('password')

        if not login or not password:
            return self._json_response(error='Login and password required', status=400)

        db = self._resolve_database(body)

        try:
            user = self._verify_credentials(login, password, db=db)
            return self._json_response(
                data=self._serialize_user(user, db=db),
            )
        except AccessDenied:
            _logger.warning('Login failed for user=%s db=%s', login, db)
            return self._json_response(
                error=f'Invalid credentials for database "{db}"',
                status=401,
            )
        except Exception as exc:
            _logger.exception('Login error for user=%s', login)
            return self._json_response(error=str(exc), status=500)

    @http.route('/api/auth/logout', type='http', auth='public', methods=['POST'], csrf=False)
    def logout(self, **kwargs):
        """Stateless logout — client clears local storage."""
        return self._json_response(data={'message': 'Logged out successfully'})

    @http.route('/api/auth/me', type='http', auth='public', methods=['GET'], csrf=False)
    def me(self, **kwargs):
        """Return user info by user_id query param."""
        user_id = kwargs.get('user_id')
        if not user_id:
            return self._json_response(error='user_id query param required', status=400)

        user = self._get_user_by_id(user_id)
        if not user:
            return self._json_response(error='User not found', status=404)

        return self._json_response(
            data=self._serialize_user(user, db=self._resolve_database()),
        )
