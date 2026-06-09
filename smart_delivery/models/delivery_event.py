from odoo import fields, models


class SmartDeliveryEvent(models.Model):
    _name = 'smart.delivery.event'
    _description = 'Delivery Real-time Event'
    _order = 'create_date desc'

    delivery_id = fields.Many2one(
        'smart.delivery.order', string='Delivery',
        required=True, ondelete='cascade', index=True,
    )
    event_type = fields.Selection([
        ('location_update', 'Location Update'),
        ('status_change', 'Status Change'),
        ('eta_update', 'ETA Update'),
        ('delay_alert', 'Delay Alert'),
        ('notification', 'Notification'),
    ], string='Event Type', required=True)
    payload = fields.Text(string='Payload (JSON)')
    is_consumed = fields.Boolean(string='Consumed', default=False, index=True)
