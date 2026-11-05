# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    pos_cash_out_receipt_required = fields.Boolean(related='pos_config_id.cash_out_receipt_required',
                                                   readonly=False)
