import uuid
import qrcode
import base64
import requests  # Added for Shelly API
from requests.auth import HTTPBasicAuth  # Added for Shelly API
from io import BytesIO
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from markupsafe import Markup
import logging

_logger = logging.getLogger(__name__)

# --- SHELLY CONFIGURATION ---
SHELLY_HOST = "https://key.akhlaghi-network.om/"
SHELLY_USER = "admin"
SHELLY_PASS = "admin"

class VisitorPass(models.Model):
    _name = 'visitor.pass'
    _description = 'Visitor Pass'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'planned_check_in desc'

    def _get_default_host_employee_id(self):
        """
        Get the default employee_id for the current user if they are an employee.
        """
        return self.env.user.employee_id

    def _default_access_token(self):
        return str(uuid.uuid4())

    name = fields.Char(string="Visit Subject", compute="_compute_name", store=True)
    host_employee_id = fields.Many2one(
        'hr.employee',
        string='Host Employee',
        required=True,
        tracking=True,
        default=_get_default_host_employee_id
    )
    
    # Visitor Details
    visitor_id = fields.Many2one('res.partner', string='Existing Visitor')
    visitor_name = fields.Char(string='Visitor Name', required=True, tracking=True)
    visitor_phone = fields.Char(string='Visitor Phone', required=True, tracking=True)
    visitor_email = fields.Char(string='Visitor Email', tracking=True)
    visitor_company = fields.Char(string='Visitor Company', tracking=True)

    reason_for_visit = fields.Text(string='Reason for Visit', tracking=True)
    
    # Time Management
    planned_check_in = fields.Datetime(
        string='Planned Check-In',
        default=fields.Datetime.now,
        required=True,
        tracking=True
    )
    check_in_time = fields.Datetime(string='Actual Check-In Time', tracking=True, readonly=True)
    check_out_time = fields.Datetime(string='Actual Check-Out Time', tracking=True, readonly=True)
    
    # Check-in/out method tracking
    check_in_by = fields.Selection([
        ('qr', 'QR Scan'), 
        ('security', 'Security Team')
    ], string='Check-In Method', readonly=True, copy=False)
    check_out_by = fields.Selection([
        ('qr', 'QR Scan'), 
        ('security', 'Security Team')
    ], string='Check-Out Method', readonly=True, copy=False)
    
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed (Awaiting Visitor)'),
        ('checked_in', 'Checked In'),
        ('checked_out', 'Checked Out'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', required=True, tracking=True)
    
    notes = fields.Text(string='Notes')

    # QR Code and Access
    access_token = fields.Char(
        string='Access Token',
        default=_default_access_token,
        required=True,
        copy=False,
        readonly=True
    )
    qr_code = fields.Binary(string="QR Code", compute="_compute_qr_code", store=True)

    @api.depends('visitor_id', 'visitor_name', 'host_employee_id')
    def _compute_name(self):
        for rec in self:
            visitor_name = rec.visitor_name or (rec.visitor_id and rec.visitor_id.name)
            host_name = rec.host_employee_id and rec.host_employee_id.name
            if visitor_name and host_name:
                rec.name = f"{visitor_name} visiting {host_name}"
            elif visitor_name:
                rec.name = visitor_name
            else:
                rec.name = "New Visit"

    @api.onchange('visitor_id')
    def _onchange_visitor_id(self):
        """
        When selecting an existing visitor, auto-fill their details.
        """
        if self.visitor_id:
            self.visitor_name = self.visitor_id.name
            self.visitor_phone = self.visitor_id.phone
            self.visitor_email = self.visitor_id.email
            self.visitor_company = self.visitor_id.parent_id.name if self.visitor_id.parent_id else ''

    @api.model_create_multi
    def create(self, vals_list):
        """
        On creation, if no visitor_id is provided, create a new res.partner
        (contact) for the visitor.
        """
        for vals in vals_list:
            if not vals.get('visitor_id') and vals.get('visitor_name') and vals.get('visitor_phone'):
                
                visitor = self.env['res.partner'].search([
                    ('name', 'ilike', vals.get('visitor_name')),
                    ('phone', '=', vals.get('visitor_phone'))
                ], limit=1)
                
                if not visitor:
                    partner_vals = {
                        'name': vals.get('visitor_name'),
                        'phone': vals.get('visitor_phone'),
                        'email': vals.get('visitor_email'),
                    }
                    if vals.get('visitor_company'):
                        company = self.env['res.partner'].search([
                            ('name', '=', vals.get('visitor_company')),
                            ('is_company', '=', True)
                        ], limit=1)
                        if not company:
                            company = self.env['res.partner'].create({
                                'name': vals.get('visitor_company'),
                                'is_company': True
                            })
                        partner_vals['parent_id'] = company.id
                    
                    visitor = self.env['res.partner'].create(partner_vals)
                
                vals['visitor_id'] = visitor.id
        
        return super().create(vals_list)

    def write(self, vals):
        """
        If updating visitor details manually, also update the linked partner.
        """
        if 'visitor_name' in vals or 'visitor_phone' in vals or 'visitor_email' in vals:
            for rec in self.filtered(lambda r: r.visitor_id):
                partner_vals = {}
                if 'visitor_name' in vals:
                    partner_vals['name'] = vals['visitor_name']
                if 'visitor_phone' in vals:
                    partner_vals['phone'] = vals['visitor_phone']
                if 'visitor_email' in vals:
                    partner_vals['email'] = vals['visitor_email']
                if partner_vals:
                    rec.visitor_id.write(partner_vals)
        
        return super().write(vals)
    
    @api.depends('access_token')
    def _compute_qr_code(self):
        """
        Generate a QR code containing ONLY the access token.
        """
        for rec in self:
            if rec.access_token:
                qr = qrcode.QRCode(
                    version=1,
                    error_correction=qrcode.constants.ERROR_CORRECT_L,
                    box_size=10,
                    border=4,
                )
                qr.add_data(rec.access_token)
                qr.make(fit=True)
                img = qr.make_image(fill_color="black", back_color="white")
                temp = BytesIO()
                img.save(temp, format="PNG")
                rec.qr_code = base64.b64encode(temp.getvalue())
            else:
                rec.qr_code = False

    def _send_qr_email(self):
        """
        Sends the confirmation and QR code email to the visitor.
        """
        self.ensure_one()
        
        template = self.env.ref('cs_visitor_management.mail_template_visitor_pass_confirmation', raise_if_not_found=False)
        if not template:
            _logger.error("Mail template 'cs_visitor_management.mail_template_visitor_pass_confirmation' not found.")
            raise UserError(_("The mail template for the visitor pass is missing. Please contact your administrator."))

        try:
            template.send_mail(self.id, force_send=True)
            _logger.info(f"Visitor pass email sent successfully to {self.visitor_email} for pass {self.id}.")
        
        except Exception as e:
            _logger.error(f"Failed during standard mail send for pass {self.id}: {e}", exc_info=True)
            raise UserError(_("Failed to send email. Please check the template or server logs.\n\nError: %s") % e)

    def _notify_employee_of_arrival(self):
        """
        Posts a message to the host employee's chatter when the visitor arrives.
        """
        self.ensure_one()
        if self.host_employee_id and self.host_employee_id.user_id:
            message_body = Markup("""
                Your visitor, <b>%s</b>, has arrived and is waiting for you at reception.
                <br/><br/>
                <b>Visit Details:</b>
                <ul>
                    <li><b>Visitor:</b> %s</li>
                    <li><b>Phone:</b> %s</li>
                    <li><b>Company:</b> %s</li>
                    <li><b>Reason:</b> %s</li>
                </ul>
            """) % (
                self.visitor_name,
                self.visitor_name,
                self.visitor_phone,
                self.visitor_company or 'N/A',
                self.reason_for_visit or 'N/A'
            )
            
            self.message_post(
                body=message_body,
                subject=f'Visitor Arrival: {self.visitor_name}',
                message_type='comment',
                subtype_xmlid='mail.mt_comment',
                partner_ids=[self.host_employee_id.user_id.partner_id.id]
            )
            
            note = f"{self.visitor_name} is waiting for you at reception."
            self.env['mail.activity'].create({
                'res_id': self.id,
                'res_model_id': self.env['ir.model']._get(self._name).id,
                'activity_type_id': self.env.ref('mail.mail_activity_data_todo').id,
                'summary': f'Visitor Arrived: {self.visitor_name}',
                'note': note,
                'user_id': self.host_employee_id.user_id.id,
                'date_deadline': fields.Date.today(),
            })

    def _notify_employee_of_confirmation(self):
        """
        Posts a message to the host's chatter with the QR code
        when the pass is confirmed.
        """
        self.ensure_one()
        if self.host_employee_id and self.host_employee_id.user_id:
            attachment = self.env['ir.attachment'].create({
                'name': f'Visitor_Pass_QR_{self.visitor_name}.png',
                'datas': self.qr_code, 
                'res_model': self._name,
                'res_id': self.id,
            })
            
            message_body = Markup("""
                <p>The visitor pass for <b>%s</b> has been confirmed.</p>
                <p>The visitor has been emailed their QR code. A copy is attached for your reference.</p>
            """) % self.visitor_name

            self.message_post(
                body=message_body,
                subject=f'Visitor Pass Confirmed: {self.visitor_name}',
                message_type='comment',
                subtype_xmlid='mail.mt_comment',
                partner_ids=[self.host_employee_id.user_id.partner_id.id],
                attachment_ids=[attachment.id] 
            )

    # --- DOOR OPENING LOGIC ---

    def _trigger_door_unlock(self):
        """
        Triggers the Shelly relay to open the door.
        Sends a request to turn the relay OFF.
        Can be called from Kiosk or Backend.
        """
        try:
            # Handle URL formatting
            base_url = SHELLY_HOST.rstrip('/')
            if base_url.startswith("http"):
                target_url = f"{base_url}/relay/0?turn=off"
            else:
                target_url = f"http://{base_url}/relay/0?turn=off"

            _logger.info(f"Opening Door via Shelly API: {target_url}")
            
            response = requests.get(
                target_url,
                auth=HTTPBasicAuth(SHELLY_USER, SHELLY_PASS),
                timeout=5
            )
            
            if response.status_code == 200:
                _logger.info(f"Door Open Signal Success: {response.text}")
                return True
            else:
                _logger.warning(f"Door Open Signal Failed: HTTP {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            _logger.error(f"Door Open Exception: {e}")
            return False

    # --- ACTION BUTTONS ---

    def action_confirm(self):
        """
        Employee confirms the visit.
        """
        self.ensure_one()
        
        if not self.visitor_email:
            raise UserError(_("You must provide a 'Visitor Email' to send the QR code."))
            
        self.write({'state': 'confirmed'})
        
        try:
            self._send_qr_email() 
        except Exception as e:
            _logger.error(f"Failed to send visitor pass email for {self.id}: {e}", exc_info=True)
            raise e
            
        self._notify_employee_of_confirmation()
        return True

    # --- CHECK-IN / CHECK-OUT METHODS ---
    
    def _do_check_in(self, by='qr'):
        """
        Internal check-in logic.
        Triggers Door Open logic.
        """
        self.ensure_one()
        if self.state not in ('confirmed', 'cancelled'):
            raise UserError(_("This visitor pass cannot be checked in. It may already be active or completed."))
            
        self.write({
            'state': 'checked_in',
            'check_in_time': fields.Datetime.now(),
            'check_in_by': by
        })
        self._notify_employee_of_arrival()
        
        # Open the door
        self._trigger_door_unlock()
        
        return True

    def _do_check_out(self, by='qr'):
        """
        Internal check-out logic.
        Triggers Door Open logic.
        """
        self.ensure_one()
        if self.state not in ('checked_in'):
            raise UserError(_("This visitor pass cannot be checked out. It is not currently checked in."))
            
        self.write({
            'state': 'checked_out',
            'check_out_time': fields.Datetime.now(),
            'check_out_by': by
        })
        
        # Open the door
        self._trigger_door_unlock()
        
        return True
    

    def action_check_in(self):
        """Called by Security/Kiosk BUTTON."""
        return self._do_check_in(by='security')
        
    def action_check_out(self):
        """Called by Security/Kiosk BUTTON."""
        return self._do_check_out(by='security')

    def action_cancel(self):
        self.write({'state': 'cancelled'})
        return True
        
    def action_reset_to_draft(self):
        self.write({
            'state': 'draft',
            'check_in_by': False,
            'check_out_by': False
        })
        return True
