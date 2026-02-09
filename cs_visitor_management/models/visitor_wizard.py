# from odoo import models, fields, api, _
# from odoo.exceptions import UserError


# class VisitorCheckinWizard(models.TransientModel):
#     _name = 'visitor.checkin.wizard'
#     _description = 'Visitor Check-in Wizard'

#     # Wizard state management
#     step = fields.Selection([
#         ('visitor_details', 'Visitor Details'),
#         ('employee_details', 'Employee Details'),
#         ('confirmation', 'Confirmation'),
#     ], string='Step', default='visitor_details', required=True)

#     # Visitor Information (Step 1)
#     visitor_name = fields.Char(string='Name', help='Visitor full name')
#     visitor_phone = fields.Char(string='Phone Number', help='Contact number')
#     visitor_company = fields.Char(string='Company', help='Company name (optional)')

#     # Employee Selection (Step 2)
#     employee_id = fields.Many2one('hr.employee', string='Employee to Visit')

#     # Confirmation data
#     visitor_id = fields.Many2one('visitor.visitor', string='Created Visitor', readonly=True)
#     confirmation_message = fields.Html(string='Confirmation', readonly=True)

#     def action_next_step(self):
#         """Move to employee details step"""
#         self.ensure_one()
        
#         if self.step == 'visitor_details':
#             if not self.visitor_name or not self.visitor_phone:
#                 raise UserError(_('Please fill in all required fields (Name and Phone Number).'))
#             return self._return_wizard_action('employee_details')
        
#         return True

#     def action_back_step(self):
#         """Go back to previous step"""
#         self.ensure_one()
        
#         if self.step == 'employee_details':
#             return self._return_wizard_action('visitor_details')
        
#         return True

#     def action_confirm(self):
#         """Create visitor record and show confirmation"""
#         self.ensure_one()
        
#         if self.step == 'employee_details':
#             if not self.employee_id:
#                 raise UserError(_('Please select an employee to visit.'))
            
#             visitor = self.env['visitor.visitor'].create({
#                 'name': self.visitor_name,
#                 'phone': self.visitor_phone,
#                 'company': self.visitor_company,
#                 'employee_id': self.employee_id.id,
#             })
            
#             self.visitor_id = visitor.id
#             self.confirmation_message = f"""
#                 <div style="text-align: center; padding: 20px;">
#                     <h2 style="color: #00a09d; font-size: 48px;">✓ All Set!</h2>
#                     <p style="font-size: 22px; margin-top: 25px;">
#                         <strong>{self.employee_id.name}</strong> has been notified of your arrival.
#                     </p>
#                     <p style="font-size: 20px; color: #555; margin-top: 20px;">
#                         Please have a seat, they will be with you shortly.
#                     </p>
#                 </div>
#             """
            
#             return self._return_wizard_action('confirmation')
        
#         return True

#     def action_new_checkin(self):
#         """Reset wizard for new check-in"""
#         self.ensure_one()
        
#         new_wizard = self.create({'step': 'visitor_details'})
        
#         return self._return_wizard_action('visitor_details', wizard_id=new_wizard.id)

#     def _return_wizard_action(self, step, wizard_id=None):
#         """Return action to display wizard at specific step"""
#         if wizard_id is None:
#             wizard_id = self.id
#             self.step = step
        
#         return {
#             'type': 'ir.actions.act_window',
#             'name': 'Visitor Check-In',
#             'res_model': self.env.context.get('res_model') or self._name,
#             'view_mode': 'form',
#             'res_id': wizard_id,
#             'target': 'fullscreen',
#             'context': {'form_view_initial_mode': 'edit'},
#         }

#     def action_open_kiosk(self):
#         """Open kiosk welcome screen"""
#         return {
#             'type': 'ir.actions.act_url',
#             'url': '/visitor/kiosk',
#             'target': 'self',
#         }
