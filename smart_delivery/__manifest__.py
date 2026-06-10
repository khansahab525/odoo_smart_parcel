{
    'name': 'Smart Last Mile Delivery',
    'version': '17.2',
    'category': 'Inventory/Delivery',
    'summary': 'AI-powered last mile delivery with GPS tracking',
    'description': """
Smart Last Mile Delivery System
================================
- Order and driver management
- GPS tracking with live map updates
- Proof of delivery (photo + signature) with confirmation PIN
- Customer ratings and feedback
- Delivery statistics dashboard
- OpenAI integration for chatbot and smart notifications
- REST API for Flutter mobile app
    """,
    'author': 'FYP Project',
    'website': 'https://www.example.com',
    'depends': ['base', 'mail'],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'views/driver_views.xml',
        'views/delivery_order_views.xml',
        'views/gps_log_views.xml',
        'views/res_users_views.xml',
        'views/menu_views.xml',
        'data/ir_config_parameter_data.xml',
        'data/demo_data.xml',
    ],
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
