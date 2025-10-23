{
    'name': 'Visitor Management',
    'version': '17.0.3.0.0', # <-- I have incremented this from 17.0.2.0.0
    'category': 'Human Resources',
    'summary': 'Visitor Pass and Kiosk Management System',
    'description': """
New Visitor Pass Workflow with Hybrid Kiosk:
- Employees can pre-register visitors.
- System generates a QR code and emails it to the visitor.
- Kiosk/Security can scan the QR code for check-in.
- Kiosk also supports walk-in visitor registration.
- Employees can manage meeting start/end times.
- Granular access rights for Employees, Security, and Managers.
    """,
    'author': 'Concept Solutions ',
    'website': 'https://www.csloman.com',
    'depends': [
        'base', 
        'hr', 
        'mail', 
        'web', 
        'contacts',  # For res.partner (Visitors)
        'barcodes'   # For QR Code generation
    ],
    'data': [
        'security/visitor_security.xml',
        'security/ir.model.access.csv',
        'data/visitor_pass_mail_template.xml',
        'views/visitor_pass_views.xml',
        'views/kiosk_templates.xml',
        'views/menu_views.xml',  # Correct file path
    ],
    'external_dependencies': {
        'python': ['qrcode'],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
}