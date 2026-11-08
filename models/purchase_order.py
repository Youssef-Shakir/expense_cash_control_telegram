# -*- coding: utf-8 -*-
from odoo import api, models


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    def _receipt_from_context(self):
        receipt_id = self.env.context.get('ecc_receipt_id')
        return self.env['ecc.receipt'].browse(receipt_id).exists() if receipt_id else self.env['ecc.receipt']

    @api.model
    def default_get(self, fields_list):
        # prefilled here, not with default_* context keys that would leak into lines, pickings and bills
        values = super().default_get(fields_list)
        receipt = self._receipt_from_context()
        if receipt:
            values.update({k: v for k, v in receipt._purchase_defaults().items() if k in fields_list})
        return values

    @api.model_create_multi
    def create(self, vals_list):
        orders = super().create(vals_list)
        receipt = self._receipt_from_context()
        if receipt and len(orders) == 1 and not receipt.purchase_order_id and (
                receipt.state == 'to_review' or receipt.vendor_payment):
            receipt._link_purchase_order(orders)
        return orders

    def action_create_invoice(self):
        """The vendor bill of an order made from a Telegram receipt gets the photos too."""
        result = super().action_create_invoice()
        receipts = self.env['ecc.receipt'].search([('purchase_order_id', 'in', self.ids)])
        for receipt in receipts:
            for bill in receipt.purchase_order_id.invoice_ids.filtered(
                    lambda m: not self.env['ir.attachment'].search_count(
                        [('res_model', '=', 'account.move'), ('res_id', '=', m.id)])):
                bill.message_post(body=receipt._get_html_link(), attachment_ids=receipt._copy_photos(bill).ids)
        return result
