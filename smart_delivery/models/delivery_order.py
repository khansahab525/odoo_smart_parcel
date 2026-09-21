import random

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


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
    requested_driver_id = fields.Many2one(
        'smart.driver',
        string='Driver to Offer',
        domain=[('is_active', '=', True)],
        tracking=True,
    )
    assignment_method = fields.Selection([
        ('preferred', 'Customer Preferred'),
        ('nearby', 'Nearby Broadcast'),
        ('admin', 'Admin Offer'),
        ('forced', 'Admin Forced'),
    ], string='Assignment Method', readonly=True, tracking=True)
    assignment_accepted_at = fields.Datetime(
        string='Assignment Accepted At', readonly=True, copy=False
    )
    offer_ids = fields.One2many(
        'smart.delivery.offer',
        'delivery_id',
        string='Driver Offers',
        copy=False,
    )
    status = fields.Selection([
        ('created', 'Created'),
        ('finding_driver', 'Finding Driver'),
        ('awaiting_acceptance', 'Awaiting Acceptance'),
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

    parcel_size = fields.Selection([
        ('document', 'Document'),
        ('small', 'Small Parcel'),
        ('medium', 'Medium Box'),
        ('large', 'Large Parcel'),
    ], string='Parcel Size', default='small', required=True, tracking=True)
    parcel_weight_kg = fields.Float(
        string='Weight (kg)', default=1.0, required=True, tracking=True
    )
    parcel_description = fields.Char(string='Parcel Contents')
    is_fragile = fields.Boolean(string='Fragile', tracking=True)
    delivery_notes = fields.Text(string='Delivery Instructions')
    scheduled_at = fields.Datetime(
        string='Scheduled Delivery', tracking=True,
        help='Leave empty for the earliest available pickup.'
    )
    estimated_distance_km = fields.Float(
        string='Estimated Distance (km)', digits=(10, 2), readonly=True
    )
    estimated_price = fields.Monetary(
        string='Estimated Price', currency_field='currency_id',
        readonly=True, tracking=True
    )
    currency_id = fields.Many2one(
        'res.currency', string='Currency', required=True,
        default=lambda self: self.env.company.currency_id
    )

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

    @api.constrains('parcel_weight_kg')
    def _check_parcel_weight(self):
        for order in self:
            if order.parcel_weight_kg <= 0 or order.parcel_weight_kg > 100:
                raise ValidationError(
                    'Parcel weight must be greater than 0 and no more than 100 kg.'
                )

    @api.onchange('driver_id')
    def _onchange_driver_id(self):
        """Reflect assignment immediately in the Odoo form status bar."""
        if self.driver_id and self.status == 'created':
            self.status = 'assigned'
        elif not self.driver_id and self.status == 'assigned':
            self.status = 'created'

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'smart.delivery.order'
                ) or 'New'
            if not vals.get('confirmation_pin'):
                vals['confirmation_pin'] = f'{random.randint(0, 9999):04d}'
            if (
                vals.get('driver_id')
                and vals.get('status', 'created')
                in ('created', 'finding_driver', 'awaiting_acceptance')
            ):
                vals['status'] = 'assigned'
        return super().create(vals_list)

    def write(self, vals):
        """Auto-update status when a driver is assigned or removed from the UI."""
        notify_orders = self.env['smart.delivery.order']
        if 'driver_id' in vals and 'status' not in vals:
            if len(self) == 1:
                self._apply_driver_status_vals(vals)
                if vals.get('driver_id') and self.status == 'created' and not self.driver_id:
                    notify_orders = self
            else:
                result = True
                for order in self:
                    order_vals = dict(vals)
                    if order._apply_driver_status_vals(order_vals):
                        notify_orders |= order
                    result = result and super(
                        SmartDeliveryOrder, order
                    ).write(order_vals)
                if notify_orders:
                    self._notify_driver_assigned(notify_orders)
                return result

        res = super().write(vals)
        if notify_orders:
            self._notify_driver_assigned(notify_orders)
        return res

    def _apply_driver_status_vals(self, vals):
        """Set status in vals when driver assignment changes. Returns True if newly assigned."""
        self.ensure_one()
        new_driver = vals.get('driver_id')
        if new_driver and self.status in (
            'created', 'finding_driver', 'awaiting_acceptance'
        ):
            vals['status'] = 'assigned'
            return not self.driver_id
        if not new_driver and self.status == 'assigned':
            vals['status'] = 'created'
        return False

    def action_send_driver_offer(self):
        from ..services.delivery_service import DeliveryService
        service = DeliveryService(self.env)
        for order in self:
            if not order.requested_driver_id:
                raise UserError('Select an active driver before sending an offer.')
            service.offer_driver(
                order,
                order.requested_driver_id,
                source='admin',
            )
        return True

    def action_broadcast_nearby(self):
        from ..services.delivery_service import DeliveryService
        service = DeliveryService(self.env)
        for order in self:
            service.broadcast_to_nearby_drivers(order)
        return True

    def action_force_assign_driver(self):
        from ..services.delivery_service import DeliveryService
        service = DeliveryService(self.env)
        for order in self:
            if not order.requested_driver_id:
                raise UserError('Select an active driver before forcing assignment.')
            service.force_assign_driver(order, order.requested_driver_id)
        return True

    @api.model
    def _cron_expire_delivery_offers(self):
        from ..services.delivery_service import DeliveryService
        DeliveryService(self.env).expire_pending_offers()

    def _notify_driver_assigned(self, orders):
        from ..services.delivery_service import DeliveryService
        service = DeliveryService(self.env)
        for order in orders:
            if order.driver_id and order.status == 'assigned':
                service._send_notification(order, 'assigned')

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
            'requested_driver_id': False,
            'assignment_method': False,
            'assignment_accepted_at': False,
        })
        return super().copy(default)
