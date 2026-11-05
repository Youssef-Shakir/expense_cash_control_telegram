# -*- coding: utf-8 -*-
from odoo import api, fields, models


class PosCashMove(models.Model):
    _inherit = 'pos.cash.move'

    receipt_ids = fields.One2many('ecc.receipt', 'cash_move_id', string='Receipts')
    receipt_count = fields.Integer('Receipt Count', compute='_compute_receipt_count', store=True)

    @api.depends('receipt_ids')
    def _compute_receipt_count(self):
        for move in self:
            move.receipt_count = len(move.receipt_ids)

    def action_view_receipts(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('expense_cash_control_telegram.action_ecc_receipt')
        action['domain'] = [('cash_move_id', '=', self.id)]
        action['context'] = {}
        return action

    def action_match_receipt(self):
        """Row button in the receipt's suggestions: this cash-out is the one the receipt proves."""
        self.ensure_one()
        receipt = self.env['ecc.receipt'].browse(self.env.context.get('ecc_receipt_id')).exists()
        if not receipt:
            return False
        return receipt._match_cash_move(self)
