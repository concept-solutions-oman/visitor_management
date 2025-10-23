from odoo import models, fields, api, _

class Visitor(models.Model):
    _name = 'visitor.visitor'
    _description = 'Visitor Record'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'check_in_time desc'

    def _get_default_employee_id(self):
        """
        Get the default employee_id for the current user.
        Only default if the user is an employee but NOT a manager.
        """
        if self.env.user.has_group('visitor_management.group_visitor_employee') and \
           not self.env.user.has_group('visitor_management.group_visitor_manager'):
            return self.env.user.employee_id
        return False

    name = fields.Char(string='Visitor Name', required=True, tracking=True)
    phone = fields.Char(string='Phone Number', required=True, tracking=True)
    company = fields.Char(string='Company', tracking=True)
    employee_id = fields.Many2one(
        'hr.employee',
        string='Visiting Employee',
        required=True,
        tracking=True,
        ondelete='restrict',
        default=_get_default_employee_id  # Added this default
    )
    check_in_time = fields.Datetime(
        string='Check-In Time',
        default=fields.Datetime.now,
        required=True,
        tracking=True
    )
    check_out_time = fields.Datetime(string='Check-Out Time', tracking=True)
    
    reason_for_visit = fields.Char(string='Reason for Visit', tracking=True)

    state = fields.Selection([
        ('checked_in', 'Checked In'),
        ('checked_out', 'Checked Out'),
    ], string='Status', default='checked_in', required=True, tracking=True)
    
    notes = fields.Text(string='Notes')

    @api.model_create_multi
    def create(self, vals_list):
        """ 
        Ensures _notify_employee is called upon creation.
        """
        visitors = super().create(vals_list)
        for visitor in visitors:
            visitor._notify_employee()
        return visitors

    def _notify_employee(self):
        """
        Posts a message to the employee's chatter feed and creates an activity.
        Updated for better HTML formatting.
        """
        self.ensure_one()
        if self.employee_id and self.employee_id.user_id:
            
            # Format Check-In Time
            check_in_time_str = self.check_in_time.strftime('%Y-%m-%d %H:%M:%S')
            
            # Build HTML message body for chatter
            company_html = f"Company: {self.company}" if self.company else " Company: N/A"
            reason_html = f"Reason: {self.reason_for_visit}" if self.reason_for_visit else "Reason: N/A"
            
            message_body = f"""
                New Visitor Check-In :   
                  Please welcome your visitor at the reception:
                    Visitor: {self.name} , 
                    Phone: {self.phone} , 
                    {company_html} ,
                    {reason_html} , 
                    Check-In Time: {check_in_time_str} , 

                  """
            
            # Post message to visitor record
            self.message_post(
                body=message_body,
                subject=f'New Visitor: {self.name}',
                message_type='notification',
                subtype_xmlid='mail.mt_note',
            )
            
            # Notify the employee
            self.message_subscribe(partner_ids=[self.employee_id.user_id.partner_id.id])
            
            # Create a concise Activity Note
            note = f"{self.name} is waiting for you at reception."
            
            details = []
            if self.company:
                details.append(f"From: {self.company}")
            if self.reason_for_visit:
                details.append(f"Reason: {self.reason_for_visit}")
                
            if details:
                note += f"\n({' / '.join(details)})"
                
            self.env['mail.activity'].create({
                'res_id': self.id,
                'res_model_id': self.env['ir.model']._get('visitor.visitor').id,
                'activity_type_id': self.env.ref('mail.mail_activity_data_todo').id,
                'summary': f'Visitor: {self.name}',
                'note': note,
                'user_id': self.employee_id.user_id.id,
                'date_deadline': fields.Date.today(),
            })

    def action_check_out(self):
        """
        Mark visitor as checked out.
        """
        self.ensure_one()
        self.write({
            'check_out_time': fields.Datetime.now(),
            'state': 'checked_out'
        })
        return True

    def name_get(self):
        """
        Customizes the display name of the visitor record.
        """
        result = []
        for record in self:
            name = f"{record.name} - {record.employee_id.name} ({record.check_in_time.strftime('%Y-%m-%d %H:%M')})"
            result.append((record.id, name))
        return result
