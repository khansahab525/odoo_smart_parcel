import random

from odoo import api, fields, models


class SmartDeliveryOrder(models.Model):
    _name = 'smart.delivery.order'
    _description = 'Smart Delivery Order'
    _order = 'create_date desc'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(
        string='Order Reference', required=True, copy=False,
        readonly=True, default='New'
    )
    customer_name = fields.Char(string='Customer Name', required=True, tracking=True)
    customer_phone = fields.Char(string='Customer Phone', tracking=True)
    customer_user_id = fields.Many2one(
        'res.users', string='Customer User', ondelete='set null'
    )

    pickup_lat = fields.Float(string='Pickup Latitude', digits=(10, 7), required=True)
    pickup_lng = fields.Float(string='Pickup Longitude', digits=(10, 7), required=True)
    delivery_lat = fields.Float(string='Delivery Latitude', digits=(10, 7), required=True)
    delivery_lng = fields.Float(string='Delivery Longitude', digits=(10, 7), required=True)
    current_lat = fields.Float(string='Current Latitude', digits=(10, 7))
    current_lng = fields.Float(string='Current Longitude', digits=(10, 7))

    driver_id = fields.Many2one('smart.driver', string='Driver', tracking=True)
    status = fields.Selection([
        ('created', 'Created'),
        ('assigned', 'Assigned'),
        ('picked_up', 'Picked Up'),
        ('in_transit', 'In Transit'),
        ('out_for_delivery', 'Out for Delivery'),
        ('delivered', 'Delivered'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='created', required=True, tracking=True)

    last_movement_time = fields.Datetime(string='Last Movement Time')
    last_speed = fields.Float(string='Last Speed (km/h)')

    pickup_address = fields.Char(string='Pickup Address')
    delivery_address = fields.Char(string='Delivery Address')

    confirmation_pin = fields.Char(
        string='Confirmation PIN', readonly=True, copy=False,
        help='4-digit code the customer shares with the driver at handover.'
    )

    pod_image = fields.Binary(string='POD Photo', attachment=True, copy=False)
    pod_signature = fields.Binary(string='POD Signature', attachment=True, copy=False)
    pod_timestamp = fields.Datetime(string='POD Timestamp', readonly=True, copy=False)

    rating = fields.Integer(string='Customer Rating', default=0, readonly=True, copy=False)
    feedback = fields.Text(string='Customer Feedback', readonly=True, copy=False)

    gps_log_ids = fields.One2many('smart.gps.log', 'delivery_id', string='GPS Logs')
    notification_log = fields.Text(string='Notification Log')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'smart.delivery.order'
                ) or 'New'
            if not vals.get('confirmation_pin'):
                vals['confirmation_pin'] = f'{random.randint(0, 9999):04d}'
        return super().create(vals_list)

    def copy(self, default=None):
        """Duplicate as a fresh order with new reference, PIN, and no POD data."""
        default = dict(default or {})
        default.update({
            'name': self.env['ir.sequence'].next_by_code(
                'smart.delivery.order'
            ) or 'New',
            'confirmation_pin': f'{random.randint(0, 9999):04d}',
            'pod_image': False,
            'pod_signature': False,
            'pod_timestamp': False,
            'rating': 0,
            'feedback': False,
            'status': 'created',
            'notification_log': False,
            'current_lat': self.pickup_lat,
            'current_lng': self.pickup_lng,
            'last_movement_time': False,
            'last_speed': 0,
            'driver_id': False,
        })
        return super().copy(default)
