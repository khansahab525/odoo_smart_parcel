{
    'name': 'Smart Last Mile Delivery',
    'version': '17.0.1.0.0',
    'category': 'Inventory/Delivery',
    'summary': 'AI-powered last mile delivery with rule-based ETA and GPS tracking',
    'description': """
Smart Last Mile Delivery System
================================
- Order and driver management
- GPS tracking with rule-based ETA calculation
- Delay detection and risk scoring (rule-based)
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
