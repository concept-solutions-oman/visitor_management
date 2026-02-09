import logging
import uuid
import json
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
        """
        kiosk_token = str(uuid.uuid4())
        request.session['kiosk_token'] = kiosk_token
        
        return request.render('cs_visitor_management.kiosk_hybrid_welcome_screen', {
            'company': request.env.company,
        })

    @http.route('/visitor/scan/<string:access_token>', type='http', auth='public', website=True)
    def kiosk_scan_action(self, access_token, **kwargs):
        """
        This is the endpoint hit by the QR code (from pre-registration).
        """
        
        if not request.session.get('kiosk_token'):
            return request.render('cs_visitor_management.kiosk_scan_result', {
                'company': request.env.company,
                'success': False,
                'message_title': 'Scan Error',
                'message_body': 'This QR code must be scanned from the official reception kiosk.',
            })

        visitor_pass, error = self._get_visitor_pass(access_token)
        
        if error:
            return request.render('cs_visitor_management.kiosk_scan_result', {
                'company': request.env.company,
                'success': False,
                'message_title': 'Scan Error',
                'message_body': error,
            })

        try:
            message_title = "Scan Error"
            message_body = "This pass is not in a scannable state."
            success = False

            if visitor_pass.state == 'confirmed':
                # Calls model _do_check_in, which now triggers the door
                visitor_pass._do_check_in(by='qr') 
                message_title = f"Welcome, {visitor_pass.visitor_name}!"
                message_body = f"You are now checked in. {visitor_pass.host_employee_id.name} has been notified of your arrival."
                success = True
                
            elif visitor_pass.state == 'checked_in':
                 # Calls model _do_check_out, which now triggers the door
                 visitor_pass._do_check_out(by='qr')
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

            return request.render('cs_visitor_management.kiosk_scan_result', {
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
            return request.render('cs_visitor_management.kiosk_scan_result', {
                'company': request.env.company,
                'success': False,
                'message_title': 'System Error',
                'message_body': f"An error occurred while processing your request: {e}",
            })

    # --- AJAX VISITOR CHECK ---
    
    @http.route('/visitor/walkin/check', type='http', auth='public', methods=['POST'], website=True, csrf=False)
    def kiosk_check_visitor(self, **kwargs):
        """
        AJAX endpoint for the walk-in form to check if a visitor exists.
        """
        try:
            data = json.loads(request.httprequest.data)
            name = data.get('name')
            phone = data.get('phone')
            
            if not name or not phone:
                return request.make_json_response({'error': 'Full name and phone number are required.'})
            
            visitor = request.env['res.partner'].sudo().search([
                ('name', 'ilike', name),
                ('phone', '=', phone)
            ], limit=1)
            
            if visitor:
                response_data = {
                    'status': 'found',
                    'visitor_id': visitor.id,
                    'name': visitor.name,
                    'email': visitor.email,
                    'company': visitor.parent_id.name if visitor.parent_id else '',
                }
                return request.make_json_response(response_data)
            else:
                return request.make_json_response({'status': 'not_found'})
        
        except json.JSONDecodeError:
            _logger.error("Failed to decode JSON from /visitor/walkin/check", exc_info=True)
            return request.make_json_response({'error': 'Invalid JSON data received.'}, status=400)
        except Exception as e:
            _logger.error("Failed to check visitor by name/phone: %s", e, exc_info=True)
            return request.make_json_response({'error': 'An Odoo server error occurred. Please try again.'}, status=500)

    # --- ROUTES FOR WALK-IN VISITORS ---

    @http.route('/visitor/walkin', type='http', auth='public', website=True)
    def kiosk_walkin_form(self, **kwargs):
        """
        Displays the walk-in registration form (now multi-step).
        """
        try:
            employees = request.env['hr.employee'].sudo().search([
                ('user_id', '!=', False)
            ])
        except Exception as e:
            _logger.error("Failed to fetch employee list for kiosk: %s", e)
            employees = request.env['hr.employee'].sudo() 

        return request.render('cs_visitor_management.kiosk_walkin_form_screen', {
            'company': request.env.company,
            'employees': employees,
            'error_message': kwargs.get('error_message')
        })

    @http.route('/visitor/walkin/submit', type='http', auth='public', website=True, methods=['POST'])
    def kiosk_walkin_submit(self, **kwargs):
        """
        Handles the submission of the multi-step walk-in form.
        Creates a new visitor.pass and triggers the door.
        """
        required_fields = ['visitor_name', 'visitor_phone', 'employee_id']
        
        if not all(kwargs.get(f) for f in required_fields):
            employees = request.env['hr.employee'].sudo().search([
                ('user_id', '!=', False)
            ])
            return request.render('cs_visitor_management.kiosk_walkin_form_screen', {
                'company': request.env.company,
                'employees': employees,
                'error_message': "Please fill in your name, phone, and select an employee."
            })
        
        try:
            employee_id = int(kwargs.get('employee_id'))
            
            new_pass = request.env['visitor.pass'].sudo().create({
                'visitor_name': kwargs.get('visitor_name'),
                'visitor_phone': kwargs.get('visitor_phone'),
                'visitor_email': kwargs.get('visitor_email'), 
                'visitor_company': kwargs.get('visitor_company'),
                'host_employee_id': employee_id,
                'planned_check_in': fields.Datetime.now(),
                'check_in_time': fields.Datetime.now(),
                'state': 'checked_in', 
                'check_in_by': 'qr',
                'reason_for_visit': kwargs.get('reason_for_visit', 'Walk-In Registration'),
            })
            
            new_pass._notify_employee_of_arrival()
            
            # --- OPEN DOOR (Walk-in specific trigger) ---
            # We call this explicitly because we created it in 'checked_in' state
            # without calling _do_check_in()
            new_pass._trigger_door_unlock()
            
            request.env.cr.commit()

            return request.render('cs_visitor_management.kiosk_scan_result', {
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
            return request.render('cs_visitor_management.kiosk_scan_result', {
                'company': request.env.company,
                'success': False,
                'message_title': 'System Error',
                'message_body': f"An error occurred while processing your registration: {e}",
            })
