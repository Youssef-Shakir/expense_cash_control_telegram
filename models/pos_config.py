# -*- coding: utf-8 -*-
from odoo import fields, models


class PosConfig(models.Model):
    _inherit = 'pos.config'

    cash_out_receipt_required = fields.Boolean(
        string='Cash-Outs Need a Receipt',
        help='Session Review refuses "Mark as Reviewed" while a cash-out of the session has no Telegram '
             'receipt or a receipt paid by the cashier is not matched.')
