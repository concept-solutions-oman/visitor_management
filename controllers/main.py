import logging
from odoo import http, fields
from odoo.http import request

_logger = logging.getLogger(__name__)

class VisitorKioskController(http.Controller):

    def _get_visitor_pass(self, access_token):
        """Find the visitor pass and handle errors."""
        if not access_token:
            return None, "Invalid or missing access token."
            
        visitor_pass = request.env['visitor.pass'].sudo().search([
            ('access_token', '=', access_token)
        ], limit=1)
        
        if not visitor_pass:
            return None, "Visitor Pass not found. It may be invalid or expired."
            
        return visitor_pass, None

    @http.route('/visitor/kiosk', type='http', auth='public', website=True)
    def kiosk_welcome(self, **kwargs):
        """
        Displays the main Kiosk screen (Hybrid).
        This screen now features the camera scanner and a button for walk-ins.
        """
        return request.render('visitor_management.kiosk_hybrid_welcome_screen', {
            'company': request.env.company,
        })

    @http.route('/visitor/scan/<string:access_token>', type='http', auth='public', website=True)
    def kiosk_scan_action(self, access_token, **kwargs):
        """
        This is the endpoint hit by the QR code (from pre-registration).
        It finds the visitor pass and performs the correct action based on state.
        (This entire function is unchanged from before)
        """
        visitor_pass, error = self._get_visitor_pass(access_token)
        
        if error:
            return request.render('visitor_management.kiosk_scan_result', {
                'company': request.env.company,
                'success': False,
                'message_title': 'Scan Error',
                'message_body': error,
            })

        try:
            # Logic for scanning
            message_title = "Scan Error"
            message_body = "This pass is not in a scannable state."
            success = False

            if visitor_pass.state == 'confirmed':
                visitor_pass.action_check_in()
                message_title = f"Welcome, {visitor_pass.visitor_name}!"
                message_body = f"You are now checked in. {visitor_pass.host_employee_id.name} has been notified of your arrival."
                success = True
                
            elif visitor_pass.state in ('in_meeting', 'meeting_ended', 'checked_in'):
                 visitor_pass.action_check_out()
                 message_title = f"Goodbye, {visitor_pass.visitor_name}!"
                 message_body = "You have been successfully checked out."
                 success = True
                 
            elif visitor_pass.state == 'checked_out':
                message_title = "Already Checked Out"
                message_body = f"{visitor_pass.visitor_name} has already been checked out."

            elif visitor_pass.state == 'draft':
                message_title = "Visit Not Confirmed"
                message_body = "This visit is still in draft. Please ask your host to confirm it."
            
            elif visitor_pass.state == 'cancelled':
                message_title = "Visit Cancelled"
                message_body = "This visitor pass has been cancelled."
            
            if success:
                request.env.cr.commit()

            return request.render('visitor_management.kiosk_scan_result', {
                'company': request.env.company,
                'success': success,
                'message_title': message_title,
                'message_body': message_body,
                'visitor_name': visitor_pass.visitor_name,
                'host_name': visitor_pass.host_employee_id.name,
            })

        except Exception as e:
            request.env.cr.rollback() 
            _logger.exception("Error during visitor scan processing: %s", e)
            return request.render('visitor_management.kiosk_scan_result', {
                'company': request.env.company,
                'success': False,
                'message_title': 'System Error',
                'message_body': f"An error occurred while processing your request: {e}",
            })

    # --- NEW ROUTES FOR WALK-IN VISITORS ---

    @http.route('/visitor/walkin', type='http', auth='public', website=True)
    def kiosk_walkin_form(self, **kwargs):
        """
        Displays the walk-in registration form.
        Fetches employees to populate the "visiting whom" list.
        """
        try:
            employees = request.env['hr.employee'].sudo().search([
                ('user_id', '!=', False) # Only list employees who are also users
            ])
        except Exception as e:
            _logger.error("Failed to fetch employee list for kiosk: %s", e)
            employees = request.env['hr.employee'].sudo() # Empty recordset

        return request.render('visitor_management.kiosk_walkin_form_screen', {
            'company': request.env.company,
            'employees': employees,
            'error_message': kwargs.get('error_message')
        })

    @http.route('/visitor/walkin/submit', type='http', auth='public', website=True, methods=['POST'])
    def kiosk_walkin_submit(self, **kwargs):
        """
        Handles the submission of the walk-in form.
        Creates a new visitor.pass and checks it in immediately.
        """
        required_fields = ['visitor_name', 'visitor_phone', 'employee_id']
        
        # 1. Validation
        if not all(kwargs.get(f) for f in required_fields):
            employees = request.env['hr.employee'].sudo().search([('user_id', '!=', False)])
            return request.render('visitor_management.kiosk_walkin_form_screen', {
                'company': request.env.company,
                'employees': employees,
                'error_message': "Please fill in your name, phone, and select an employee."
            })
        
        try:
            employee_id = int(kwargs.get('employee_id'))
            
            # 2. Create Visitor Pass
            new_pass = request.env['visitor.pass'].sudo().create({
                'visitor_name': kwargs.get('visitor_name'),
                'visitor_phone': kwargs.get('visitor_phone'),
                'visitor_company': kwargs.get('visitor_company'),
                'host_employee_id': employee_id,
                'planned_check_in': fields.Datetime.now(),
                'check_in_time': fields.Datetime.now(),
                'state': 'checked_in', # Check-in immediately
                'reason_for_visit': 'Walk-In Registration',
            })
            
            # 3. Notify Employee
            new_pass._notify_employee_of_arrival()
            
            # 4. Commit and show success
            request.env.cr.commit()

            return request.render('visitor_management.kiosk_scan_result', {
                'company': request.env.company,
                'success': True,
                'message_title': f"Thank You, {new_pass.visitor_name}!",
                'message_body': f"{new_pass.host_employee_id.name} has been notified of your arrival. Please have a seat.",
                'visitor_name': new_pass.visitor_name,
                'host_name': new_pass.host_employee_id.name,
            })

        except Exception as e:
            request.env.cr.rollback()
            _logger.exception("Error during walk-in submission: %s", e)
            return request.render('visitor_management.kiosk_scan_result', {
                'company': request.env.company,
                'success': False,
                'message_title': 'System Error',
                'message_body': f"An error occurred while processing your registration: {e}",
            })