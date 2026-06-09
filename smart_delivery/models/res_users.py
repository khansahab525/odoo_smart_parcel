from odoo import fields, models


class ResUsers(models.Model):
    _inherit = 'res.users'

    smart_delivery_role = fields.Selection([
        ('driver', 'Driver'),
        ('customer', 'Customer'),
        ('admin', 'Admin'),
    ], string='Delivery Role', default='customer')
    smart_driver_id = fields.Many2one('smart.driver', string='Driver Profile')
    smart_customer_phone = fields.Char(string='Customer Phone')
