# -*- coding: utf-8 -*-
from odoo import fields, models, _
from odoo.exceptions import UserError


class ReceiptQuestionWizard(models.TransientModel):
    _name = 'ecc.receipt.question.wizard'
    _description = 'Ask a Question About a Receipt'

    receipt_id = fields.Many2one('ecc.receipt', required=True, readonly=True)
    sender_id = fields.Many2one(related='receipt_id.sender_id')
    chat_title = fields.Char(related='receipt_id.chat_title')
    text = fields.Text('Question', required=True)

    def action_send(self):
        self.ensure_one()
        receipt = self.receipt_id
        text = (self.text or '').strip()
        if not text:
            raise UserError(_('Write the question first.'))
        message = _('❓ %(ref)s: %(text)s', ref=receipt.name, text=text)
        service = self.env['telegram.service'].with_company(receipt.company_id)
        message_id = service.send_reply(receipt.chat_id, receipt.message_id, message)
        self.env['ecc.receipt.question'].create({
            'receipt_id': receipt.id,
            'text': text,
            'chat_id': receipt.chat_id,
            'telegram_message_id': message_id or 0,
        })
        receipt.message_post(body=_('❓ Question sent to Telegram: %s', text))
        return {'type': 'ir.actions.act_window_close'}
