# -*- coding: utf-8 -*-
from odoo import _, models
from odoo.exceptions import UserError


class ReceiptQuestionWizard(models.TransientModel):
    _inherit = 'ecc.receipt.question.wizard'

    def action_send(self):
        """A receipt sent from the app: the question goes to the sender's app instead of Telegram."""
        self.ensure_one()
        receipt = self.receipt_id
        if not receipt.app_user_id or receipt.chat_id:
            return super().action_send()
        text = (self.text or '').strip()
        if not text:
            raise UserError(_('Write the question first.'))
        self.env['ecc.receipt.question'].create({'receipt_id': receipt.id, 'text': text})
        receipt._app_tell_sender(_('Question about %s', receipt.name), text)
        receipt.message_post(body=_('❓ Question sent to the DoniaLink App: %s', text))
        return {'type': 'ir.actions.act_window_close'}
