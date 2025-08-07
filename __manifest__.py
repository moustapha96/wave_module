{
    'name': 'Wave Money Payment',
    'version': '1.0',
    'summary': 'Intégration Wave et Orange Money pour les paiements',
    'description': 'Permet de générer des liens de paiement Wave et Orange Money et de suivre les transactions.',
    'category': 'CCBM/',
    # 'depends': ['base'],
    'depends': [
        'base',
        'sale',
        'account',
        'mail',
        'orbit'
    ],
    'installable': True,
    'auto_install': False,
    'application': True,
    'images': ['static/description/icon.png'],
    'data': [
        'security/ir.model.access.csv',

        'views/wave_config_views.xml',
        'views/wave_transaction_views.xml',

        'views/wave_menu.xml',
        
        'views/sale_order_view.xml',
        # 'views/sale_order_payment_view.xml',
    ],
    'demo': [
      
    ],
    'license': 'LGPL-3',
}
