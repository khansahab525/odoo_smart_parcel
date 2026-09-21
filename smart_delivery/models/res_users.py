from odoo import api, fields, models
from odoo.exceptions import ValidationError


class ResUsers(models.Model):
    _inherit = 'res.users'

    smart_delivery_role = fields.Selection([
        ('driver', 'Driver'),
        ('customer', 'Customer'),
        ('admin', 'Admin'),
    ], string='Delivery Role', default='customer')
    smart_driver_id = fields.Many2one('smart.driver', string='Driver Profile')
    smart_customer_phone = fields.Char(string='Customer Phone')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._validate_password_length(vals.get('password'))
        return super().create(vals_list)

    def write(self, vals):
        self._validate_password_length(vals.get('password'))
        return super().write(vals)

    @staticmethod
    def _validate_password_length(password):
        if password and len(password) < 5:
            raise ValidationError('Password must be at least 5 characters.')
