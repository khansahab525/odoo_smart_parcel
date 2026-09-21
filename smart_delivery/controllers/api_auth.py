import logging
import re

from odoo import http
from odoo.exceptions import AccessDenied, ValidationError
from odoo.http import request

from .api_base import ApiBaseController

_logger = logging.getLogger(__name__)
_EMAIL_PATTERN = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


class ApiAuthController(ApiBaseController):

    @http.route(
        '/api/auth/register',
        type='http', auth='public', methods=['POST'], csrf=False
    )
    def register(self, **kwargs):
        """Create a customer account and return its authenticated profile."""
        body = self._parse_json_body()
        name = (body.get('name') or '').strip()
        username = (body.get('username') or '').strip()
        email = (body.get('email') or '').strip().lower()
        phone = (body.get('phone') or '').strip()
        password = body.get('password') or ''

        missing = [
            label for label, value in (
                ('name', name),
                ('username', username),
                ('email', email),
                ('phone', phone),
                ('password', password),
            ) if not value
        ]
        if missing:
            return self._json_response(
                error=f'Missing required fields: {", ".join(missing)}',
                status=400,
            )
        if len(name) < 2 or len(name) > 80:
            return self._json_response(
                error='Name must be between 2 and 80 characters', status=400
            )
        if len(username) < 3 or len(username) > 80:
            return self._json_response(
                error='Username must be between 3 and 80 characters', status=400
            )
        if not _EMAIL_PATTERN.fullmatch(email):
            return self._json_response(
                error='Enter a valid email address', status=400
            )
        if len(phone) < 7 or len(phone) > 30:
            return self._json_response(
                error='Enter a valid phone number', status=400
            )
        if len(password) < 5:
            return self._json_response(
                error='Password must be at least 5 characters',
                status=400,
            )

        Users = request.env['res.users'].sudo()
        if Users.search([('login', '=ilike', username)], limit=1):
            return self._json_response(
                error='This username is already in use', status=409
            )
        if Users.search([('email', '=ilike', email)], limit=1):
            return self._json_response(
                error='An account with this email already exists', status=409
            )

        try:
            portal_group = request.env.ref('base.group_portal')
            user = Users.with_context(no_reset_password=True).create({
                'name': name,
                'login': username,
                'email': email,
                'password': password,
                'groups_id': [(6, 0, [portal_group.id])],
                'smart_delivery_role': 'customer',
                'smart_customer_phone': phone,
            })
            return self._json_response(
                data=self._serialize_user(user),
                status=201,
            )
        except (ValidationError, ValueError) as exc:
            return self._json_response(error=str(exc), status=400)
        except Exception:
            _logger.exception('Customer registration failed for email=%s', email)
            return self._json_response(
                error='Unable to create account. Please try again.',
                status=500,
            )

    @http.route(
        '/api/auth/forgot-password',
        type='http', auth='public', methods=['POST'], csrf=False
    )
    def forgot_password(self, **kwargs):
        """Send Odoo's secure password-reset link without exposing accounts."""
        body = self._parse_json_body()
        email = (body.get('email') or '').strip().lower()
        if not _EMAIL_PATTERN.fullmatch(email):
            return self._json_response(
                error='Enter a valid email address', status=400
            )

        try:
            user = request.env['res.users'].sudo().search([
                '|',
                ('login', '=ilike', email),
                ('email', '=ilike', email),
                ('active', '=', True),
            ], limit=1)
            if user:
                user.action_reset_password()
        except Exception:
            _logger.exception('Password reset request failed for email=%s', email)
            return self._json_response(
                error='Unable to send reset instructions. Please try again.',
                status=500,
            )

        return self._json_response(data={
            'message': (
                'If an account exists for this email, password reset '
                'instructions have been sent.'
            ),
        })

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
                data=self._serialize_user(user),
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
            data=self._serialize_user(user),
        )
