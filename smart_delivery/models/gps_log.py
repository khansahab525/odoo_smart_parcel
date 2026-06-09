from odoo import fields, models


class SmartGpsLog(models.Model):
    _name = 'smart.gps.log'
    _description = 'GPS Tracking Log'
    _order = 'timestamp desc'

    driver_id = fields.Many2one('smart.driver', string='Driver', required=True, ondelete='cascade')
    delivery_id = fields.Many2one(
        'smart.delivery.order', string='Delivery', ondelete='cascade'
    )
    latitude = fields.Float(string='Latitude', digits=(10, 7), required=True)
    longitude = fields.Float(string='Longitude', digits=(10, 7), required=True)
    speed = fields.Float(string='Speed (km/h)')
    timestamp = fields.Datetime(
        string='Timestamp', required=True, default=fields.Datetime.now
    )
