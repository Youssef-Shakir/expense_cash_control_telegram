# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class PosSession(models.Model):
    _inherit = 'pos.session'

    receipt_ids = fields.One2many('ecc.receipt', 'session_id', string='Telegram Receipts')
    cash_out_without_receipt_count = fields.Integer('Cash-Outs Without Receipt',
                                                    compute='_compute_receipt_review_stats')
    receipt_unmatched_count = fields.Integer('Receipts Not Matched', compute='_compute_receipt_review_stats')
    cash_out_receipt_required = fields.Boolean(related='config_id.cash_out_receipt_required')

    @api.depends('cash_move_ids.move_type', 'cash_move_ids.receipt_count', 'receipt_ids.state',
                 'receipt_ids.paid_by')
    def _compute_receipt_review_stats(self):
        for session in self:
            session.cash_out_without_receipt_count = len(session.cash_move_ids.filtered(
                lambda m: m.move_type == 'out' and not m.receipt_count))
            session.receipt_unmatched_count = len(session.receipt_ids.filtered(
                lambda r: r.state == 'to_review' and r.paid_by == 'cashier'))

    def action_cash_review_done(self):
        for session in self.filtered('config_id.cash_out_receipt_required'):
            if session.cash_out_without_receipt_count or session.receipt_unmatched_count:
                raise UserError(_(
                    'Session %(session)s needs a receipt for every cash-out: %(moves)s cash-out(s) without '
                    'receipt and %(receipts)s receipt(s) not matched.',
                    session=session.name, moves=session.cash_out_without_receipt_count,
                    receipts=session.receipt_unmatched_count))
        return super().action_cash_review_done()

    def action_view_receipts(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('expense_cash_control_telegram.action_ecc_receipt')
        action['domain'] = [('session_id', '=', self.id)]
        action['context'] = {'default_session_id': self.id}
        return action
