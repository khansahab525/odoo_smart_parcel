from odoo import api, fields, models


class SmartDriver(models.Model):
    _name = 'smart.driver'
    _description = 'Delivery Driver'
    _order = 'name'

    name = fields.Char(string='Driver Name', required=True)
    profile_image = fields.Image(
        string='Profile Picture',
        max_width=256,
        max_height=256,
    )
    phone = fields.Char(string='Phone')
    is_active = fields.Boolean(string='Active', default=True)
    is_online = fields.Boolean(string='Connected', default=False, readonly=True)
    current_lat = fields.Float(string='Current Latitude', digits=(10, 7))
    current_lng = fields.Float(string='Current Longitude', digits=(10, 7))
    last_location_time = fields.Datetime(string='Last Location Update', readonly=True)
    user_id = fields.Many2one('res.users', string='Linked User', ondelete='set null')
    assigned_delivery_ids = fields.One2many(
        'smart.delivery.order', 'driver_id', string='Assigned Deliveries'
    )
    gps_log_ids = fields.One2many('smart.gps.log', 'driver_id', string='GPS Logs')
    offer_ids = fields.One2many(
        'smart.delivery.offer', 'driver_id', string='Delivery Offers'
    )
    active_delivery_count = fields.Integer(
        string='Active Deliveries', compute='_compute_active_delivery_count'
    )

    _sql_constraints = [
        (
            'driver_user_unique',
            'unique(user_id)',
            'An Odoo user can only be linked to one driver.',
        ),
    ]

    @api.depends('assigned_delivery_ids', 'assigned_delivery_ids.status')
    def _compute_active_delivery_count(self):
        active_statuses = {'assigned', 'picked_up', 'in_transit', 'out_for_delivery'}
        for driver in self:
            driver.active_delivery_count = len(
                driver.assigned_delivery_ids.filtered(lambda d: d.status in active_statuses)
            )

    @api.model_create_multi
    def create(self, vals_list):
        drivers = super().create(vals_list)
        drivers._sync_linked_users()
        return drivers

    def write(self, vals):
        previous_users = self.mapped('user_id') if 'user_id' in vals else self.env['res.users']
        result = super().write(vals)
        if 'user_id' in vals:
            for user in previous_users:
                if (
                    user.smart_driver_id
                    and user.smart_driver_id.user_id != user
                ):
                    user.smart_driver_id = False
            self._sync_linked_users()
        return result

    def _sync_linked_users(self):
        for driver in self.filtered('user_id'):
            driver.user_id.write({
                'smart_driver_id': driver.id,
                'smart_delivery_role': 'driver',
            })
