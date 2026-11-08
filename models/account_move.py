# -*- coding: utf-8 -*-
from odoo import models


class AccountMove(models.Model):
    _inherit = 'account.move'

    def _post(self, soft=True):
        posted = super()._post(soft)
        # the bill of a purchase order made from a receipt paid in cash from the POS: the cash-out pays it
        orders = posted.filtered(lambda m: m.move_type == 'in_invoice').line_ids.purchase_line_id.order_id
        if orders:
            self.env['ecc.receipt'].sudo().search([
                ('purchase_order_id', 'in', orders.ids), ('cash_move_id', '!=', False),
            ])._reconcile_vendor_payment()
        return posted
