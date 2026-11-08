# -*- coding: utf-8 -*-
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Receipt count of a cash-out no longer counts rejected or duplicate photos."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    moves = env['pos.cash.move'].search([('receipt_ids', '!=', False)])
    env.add_to_compute(moves._fields['receipt_count'], moves)
    moves._recompute_recordset(['receipt_count'])
