# -*- coding: utf-8 -*-
from odoo import fields, models


class ExpenseCategory(models.Model):
    _inherit = 'expense.category'

    owner_box_id = fields.Many2one('ecc.owner.box', string='Owner Cash Box', readonly=True, index='btree_not_null',
                                   ondelete='cascade',
                                   help='Collection category of an owner cash box: a POS Cash Out with it moves the '
                                        'cash to that box.')
    owner_expense = fields.Boolean('Owner Expense Button',
                                   help='Offered to the owners in Telegram when they record an expense from their cash.')
