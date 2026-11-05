# -*- coding: utf-8 -*-
from odoo import models, _


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    def action_post(self):
        result = super().action_post()
        self._sync_owner_moves()
        return result

    def action_draft(self):
        result = super().action_draft()
        self._sync_owner_moves()
        return result

    def action_cancel(self):
        result = super().action_cancel()
        self._sync_owner_moves()
        return result

    def _sync_owner_moves(self):
        """A vendor payment from an owner's cash journal (e.g. the bill of a purchase order he paid) is an
        expense of his box."""
        Box = self.env['ecc.owner.box'].sudo()
        Move = self.env['ecc.owner.move'].sudo()
        for payment in self:
            box = Box.search([('journal_id', '=', payment.journal_id.id)], limit=1)
            if not box:
                continue
            existing = Move.search([('payment_id', '=', payment.id)])
            if payment.state in ('draft', 'canceled', 'rejected'):
                existing.write({'state': 'cancelled'})
                continue
            if payment.payment_type != 'outbound':
                continue
            if existing:
                existing.write({'state': 'posted', 'amount': -payment.amount})
            else:
                box._add_move('expense', -payment.amount,
                              _('Payment %(payment)s – %(partner)s', payment=payment.name,
                                partner=payment.partner_id.display_name or ''),
                              payment_id=payment.id, account_move_id=payment.move_id.id)
