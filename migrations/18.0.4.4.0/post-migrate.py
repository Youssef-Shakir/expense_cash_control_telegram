# -*- coding: utf-8 -*-
from odoo import SUPERUSER_ID, api

STATES = {'to_review': 'to_review', 'processed': 'reviewed', 'rejected': 'rejected', 'duplicate': 'rejected'}


def migrate(cr, version):
    """Owner expenses are reviewed on the owner movement (like a POS cash-out), not as receipts: the review
    state comes from the receipt, and the owner receipts still waiting in the Receipts inbox are removed (their
    photos are on the expense)."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    for model in ('ecc.owner.move', 'ecc.owner.card.move'):
        for move in env[model].search([('kind', '=', 'expense'), ('receipt_id', '!=', False)]):
            receipt = move.receipt_id
            vals = {'review_state': STATES.get(receipt.state, 'reviewed')}
            if receipt.partner_id:
                vals['vendor_id'] = receipt.partner_id.id
            move.write(vals)
    waiting = env['ecc.receipt'].search([('paid_by', '=', 'owner'), ('owner_box_id', '!=', False),
                                         ('state', '=', 'to_review'), ('expense_id', '!=', False)])
    for receipt in waiting:
        expense = receipt.expense_id
        if not expense.attachment_ids:
            copies = receipt._copy_photos(expense)
            expense.write({'attachment_ids': [(4, a.id) for a in copies]})
    waiting.unlink()
