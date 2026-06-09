from odoo import api, fields, models


class SmartDriver(models.Model):
    _name = 'smart.driver'
    _description = 'Delivery Driver'
    _order = 'name'

    name = fields.Char(string='Driver Name', required=True)
    phone = fields.Char(string='Phone')
    is_active = fields.Boolean(string='Active', default=True)
    current_lat = fields.Float(string='Current Latitude', digits=(10, 7))
    current_lng = fields.Float(string='Current Longitude', digits=(10, 7))
    user_id = fields.Many2one('res.users', string='Linked User', ondelete='set null')
    assigned_delivery_ids = fields.One2many(
        'smart.delivery.order', 'driver_id', string='Assigned Deliveries'
    )
    gps_log_ids = fields.One2many('smart.gps.log', 'driver_id', string='GPS Logs')
    active_delivery_count = fields.Integer(
        string='Active Deliveries', compute='_compute_active_delivery_count'
    )

    @api.depends('assigned_delivery_ids', 'assigned_delivery_ids.status')
    def _compute_active_delivery_count(self):
        active_statuses = {'assigned', 'picked_up', 'in_transit', 'out_for_delivery'}
        for driver in self:
            driver.active_delivery_count = len(
                driver.assigned_delivery_ids.filtered(lambda d: d.status in active_statuses)
            )
