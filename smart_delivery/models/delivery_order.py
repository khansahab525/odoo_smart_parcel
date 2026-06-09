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

    eta_minutes = fields.Integer(string='ETA (minutes)', readonly=True)
    eta_datetime = fields.Datetime(string='ETA DateTime', readonly=True)
    delay_status = fields.Selection([
        ('on_time', 'On Time'),
        ('delayed', 'Delayed'),
        ('high_risk', 'High Risk'),
    ], string='Delay Status', default='on_time', readonly=True)
    delay_reason = fields.Char(string='Delay Reason', readonly=True)
    risk_score = fields.Integer(string='Risk Score', default=0, readonly=True)
    risk_level = fields.Selection([
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
    ], string='Risk Level', default='low', readonly=True)
    traffic_level = fields.Selection([
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
    ], string='Traffic Level', default='medium')
    initial_eta_minutes = fields.Integer(string='Initial ETA (minutes)', readonly=True)
    last_movement_time = fields.Datetime(string='Last Movement Time')
    last_speed = fields.Float(string='Last Speed (km/h)')

    gps_log_ids = fields.One2many('smart.gps.log', 'delivery_id', string='GPS Logs')
    notification_log = fields.Text(string='Notification Log')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'smart.delivery.order'
                ) or 'New'
        return super().create(vals_list)
