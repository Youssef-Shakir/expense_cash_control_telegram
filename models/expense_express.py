# -*- coding: utf-8 -*-
from odoo import api, models


class ExpenseExpress(models.Model):
    _inherit = 'expense.express'

    def _receipt_from_context(self):
        receipt_id = self.env.context.get('ecc_receipt_id')
        return self.env['ecc.receipt'].browse(receipt_id).exists() if receipt_id else self.env['ecc.receipt']

    @api.model
    def default_get(self, fields_list):
        # prefilled here rather than with default_* context keys: those would leak into the
        # journal entry / bill the expense creates (default_name, default_date...)
        values = super().default_get(fields_list)
        receipt = self._receipt_from_context()
        if receipt:
            values.update({k: v for k, v in receipt._expense_defaults().items() if k in fields_list})
        return values

    @api.model_create_multi
    def create(self, vals_list):
        expenses = super().create(vals_list)
        receipt = self._receipt_from_context()
        if receipt and len(expenses) == 1 and receipt.state == 'to_review' and not receipt.expense_id:
            receipt._link_expense(expenses)
        return expenses

    def write(self, vals):
        result = super().write(vals)
        if 'amount' in vals:
            moves = self.env['ecc.owner.move'].sudo().search([('expense_id', 'in', self.ids)])
            for move in moves:
                move.amount = -move.expense_id.amount
        return result
