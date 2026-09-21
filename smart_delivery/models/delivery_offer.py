from odoo import fields, models


class SmartDeliveryOffer(models.Model):
    _name = 'smart.delivery.offer'
    _description = 'Driver Delivery Offer'
    _order = 'offered_at desc'

    delivery_id = fields.Many2one(
        'smart.delivery.order',
        string='Delivery',
        required=True,
        ondelete='cascade',
        index=True,
    )
    driver_id = fields.Many2one(
        'smart.driver',
        string='Driver',
        required=True,
        ondelete='cascade',
        index=True,
    )
    source = fields.Selection([
        ('preferred', 'Customer Preferred'),
        ('nearby', 'Nearby Broadcast'),
        ('admin', 'Admin Offer'),
    ], string='Source', required=True, default='nearby')
    status = fields.Selection([
        ('pending', 'Pending'),
        ('accepted', 'Accepted'),
        ('rejected', 'Rejected'),
        ('expired', 'Expired'),
        ('cancelled', 'Cancelled'),
    ], string='Status', required=True, default='pending', index=True)
    distance_km = fields.Float(string='Pickup Distance (km)', digits=(10, 2))
    offered_at = fields.Datetime(
        string='Offered At', required=True, default=fields.Datetime.now
    )
    expires_at = fields.Datetime(string='Expires At', required=True, index=True)
    responded_at = fields.Datetime(string='Responded At', readonly=True)

