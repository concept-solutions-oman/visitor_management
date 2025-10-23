import uuid
import qrcode
import base64
from io import BytesIO
from odoo import models, fields, api, _
from odoo.exceptions import UserError

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
    # An employee can either select an existing contact (partner)
    # or fill in the details manually to create a new one.
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
    meeting_start_time = fields.Datetime(string='Meeting Start Time', tracking=True, readonly=True)
    meeting_end_time = fields.Datetime(string='Meeting End Time', tracking=True, readonly=True)

    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed (Awaiting Visitor)'),
        ('checked_in', 'Checked In'),
        ('in_meeting', 'In Meeting'),
        ('meeting_ended', 'Meeting Ended'),
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

    @api.depends('visitor_id', 'visitor_name')
    def _compute_name(self):
        for rec in self:
            visitor_name = rec.visitor_name or rec.visitor_id.name
            rec.name = f"{visitor_name} visiting {rec.host_employee_id.name}"

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
            if not vals.get('visitor_id') and vals.get('visitor_name'):
                partner_vals = {
                    'name': vals.get('visitor_name'),
                    'phone': vals.get('visitor_phone'),
                    'email': vals.get('visitor_email'),
                }
                if vals.get('visitor_company'):
                    # Check if company exists, otherwise create it
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
                
                new_visitor = self.env['res.partner'].create(partner_vals)
                vals['visitor_id'] = new_visitor.id
        
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
        Generate a QR code containing the URL for check-in/out.
        """
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        for rec in self:
            if rec.access_token:
                qr_url = f"{base_url}/visitor/scan/{rec.access_token}"
                qr = qrcode.QRCode(
                    version=1,
                    error_correction=qrcode.constants.ERROR_CORRECT_L,
                    box_size=10,
                    border=4,
                )
                qr.add_data(qr_url)
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
        if not self.visitor_email:
            raise UserError(_("Cannot send email: Visitor does not have an email address."))
            
        template = self.env.ref('visitor_management.mail_template_visitor_pass_confirmation', raise_if_not_found=False)
        if not template:
            _logger.error("Mail template 'mail_template_visitor_pass_confirmation' not found.")
            return

        template.send_mail(self.id, force_send=True)

    def _notify_employee_of_arrival(self):
        """
        Posts a message to the host employee's chatter when the visitor arrives.
        """
        self.ensure_one()
        if self.host_employee_id and self.host_employee_id.user_id:
            # Post message to visitor pass record (and notify employee)
            message_body = f"""
                Your visitor, <b>{self.visitor_name}</b>, has arrived and is waiting for you at reception.
                <br/><br/>
                <b>Visit Details:</b>
                <ul>
                    <li><b>Visitor:</b> {self.visitor_name}</li>
                    <li><b>Phone:</b> {self.visitor_phone}</li>
                    <li><b>Company:</b> {self.visitor_company or 'N/A'}</li>
                    <li><b>Reason:</b> {self.reason_for_visit or 'N/A'}</li>
                </ul>
            """
            self.message_post(
                body=message_body,
                subject=f'Visitor Arrival: {self.visitor_name}',
                message_type='notification',
                subtype_xmlid='mail.mt_note',
                partner_ids=[self.host_employee_id.user_id.partner_id.id]
            )
            
            # Create a concise Activity
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

    # --- NEW METHOD ---
    def _notify_employee_of_confirmation(self):
        """
        Posts a message to the host's chatter with the QR code
        when the pass is confirmed.
        """
        self.ensure_one()
        if self.host_employee_id and self.host_employee_id.user_id:
            # 1. Create an attachment from the qr_code field
            attachment = self.env['ir.attachment'].create({
                'name': f'Visitor_Pass_QR_{self.visitor_name}.png',
                'datas': self.qr_code, # self.qr_code is already base64
                'res_model': self._name,
                'res_id': self.id,
            })
            
            # 2. Post a message to the host's chatter
            message_body = f"""
                <p>The visitor pass for <b>{self.visitor_name}</b> has been confirmed.</p>
                <p>The visitor has been emailed their QR code. A copy is attached for your reference.</p>
            """
            self.message_post(
                body=message_body,
                subject=f'Visitor Pass Confirmed: {self.visitor_name}',
                message_type='notification',
                subtype_xmlid='mail.mt_note',
                partner_ids=[self.host_employee_id.user_id.partner_id.id],
                attachment_ids=[attachment.id] # Attach the QR code
            )

    # --- ACTION BUTTONS ---

    def action_confirm(self):
        """
        Employee confirms the visit.
        Triggers QR code generation, email, and internal notification.
        """
        self.ensure_one()
        self.write({'state': 'confirmed'})
        self._send_qr_email()
        self._notify_employee_of_confirmation() # <-- MODIFIED: Added this line
        return True

    def action_check_in(self):
        """
        Called by Security/Kiosk to check in the visitor.
        """
        self.ensure_one()
        if self.state not in ('confirmed', 'cancelled'):
            raise UserError(_("This visitor pass cannot be checked in. It may already be active or completed."))
            
        self.write({
            'state': 'checked_in',
            'check_in_time': fields.Datetime.now()
        })
        self._notify_employee_of_arrival()
        return True

    def action_start_meeting(self):
        """
        Called by Employee to signal the meeting has started.
        """
        self.ensure_one()
        self.write({
            'state': 'in_meeting',
            'meeting_start_time': fields.Datetime.now()
        })
        return True

    def action_end_meeting(self):
        """
        Called by Employee to signal the meeting has ended.
        """
        self.ensure_one()
        self.write({
            'state': 'meeting_ended',
            'meeting_end_time': fields.Datetime.now()
        })
        return True
        
    def action_check_out(self):
        """
        Called by Security/Kiosk to check out the visitor.
        """
        self.ensure_one()
        if self.state not in ('checked_in', 'in_meeting', 'meeting_ended'):
            raise UserError(_("This visitor pass cannot be checked out. It is not currently checked in."))
            
        self.write({
            'state': 'checked_out',
            'check_out_time': fields.Datetime.now()
        })
        # If meeting wasn't manually ended, end it now.
        if not self.meeting_end_time:
             self.meeting_end_time = fields.Datetime.now()
        return True

    def action_cancel(self):
        self.write({'state': 'cancelled'})
        return True
        
    def action_reset_to_draft(self):
        self.write({'state': 'draft'})
        return True