from odoo import fields, models


class SmartFcmToken(models.Model):
    _name = 'smart.fcm.token'
    _description = 'FCM Device Token'
    _rec_name = 'device_name'

    user_id = fields.Many2one(
        'res.users', string='User', required=True,
        ondelete='cascade', index=True,
    )
    token = fields.Char(string='FCM Token', required=True, index=True)
    device_name = fields.Char(string='Device Name')
    platform = fields.Selection([
        ('android', 'Android'),
        ('ios', 'iOS'),
        ('web', 'Web'),
    ], string='Platform', default='android')
    is_active = fields.Boolean(string='Active', default=True)

    _sql_constraints = [
        ('token_user_uniq', 'unique(token, user_id)',
         'This FCM token is already registered for this user.'),
    ]
