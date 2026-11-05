# -*- coding: utf-8 -*-
from odoo import api, fields, models


class TelegramSender(models.Model):
    """A Telegram user who sent receipts. Created automatically on the first photo;
    archive it to make the bot ignore that person."""
    _name = 'ecc.telegram.sender'
    _description = 'Telegram Sender'
    _order = 'name'

    name = fields.Char('Name', required=True, help='Shown on the receipts. Rename it to the employee name.')
    telegram_user_id = fields.Char('Telegram User ID', required=True, readonly=True, index=True)
    telegram_username = fields.Char('Telegram Username', readonly=True)
    telegram_name = fields.Char('Name in Telegram', readonly=True)
    company_id = fields.Many2one('res.company', string='Company', required=True,
                                 default=lambda self: self.env.company, index=True)
    active = fields.Boolean(default=True, help='Archived senders are ignored by the bot.')
    receipt_ids = fields.One2many('ecc.receipt', 'sender_id', string='Receipts')
    receipt_count = fields.Integer('Receipt Count', compute='_compute_receipt_count')

    _sql_constraints = [
        ('telegram_user_company_unique', 'UNIQUE(telegram_user_id, company_id)',
         'This Telegram user is already known for this company.'),
    ]

    def _compute_receipt_count(self):
        data = dict(self.env['ecc.receipt']._read_group(
            [('sender_id', 'in', self.ids)], ['sender_id'], ['__count']))
        for sender in self:
            sender.receipt_count = data.get(sender, 0)

    @api.model
    def _find_or_create(self, company, telegram_user_id, name=None, username=None):
        """The sender (archived ones included), created on first contact. Telegram names are refreshed
        but a name the accountant changed is kept."""
        telegram_user_id = str(telegram_user_id)
        sender = self.with_context(active_test=False).search(
            [('telegram_user_id', '=', telegram_user_id), ('company_id', '=', company.id)], limit=1)
        display = (name or '').strip() or (username and '@%s' % username) or telegram_user_id
        if not sender:
            return self.create({
                'name': display, 'telegram_name': display, 'telegram_username': username or False,
                'telegram_user_id': telegram_user_id, 'company_id': company.id,
            })
        vals = {}
        if username and sender.telegram_username != username:
            vals['telegram_username'] = username
        if name and sender.telegram_name != display:
            if sender.name == sender.telegram_name:
                vals['name'] = display
            vals['telegram_name'] = display
        if vals:
            sender.write(vals)
        return sender

    def action_view_receipts(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('expense_cash_control_telegram.action_ecc_receipt')
        action['domain'] = [('sender_id', '=', self.id)]
        action['context'] = {'search_default_to_review': 0}
        return action
