# -*- coding: utf-8 -*-
"""A card on the DoniaLink App admin dashboard: what waits in the cash boxes and the receipts."""
from odoo import _, models


class DonialinkAppAdmin(models.AbstractModel):
    _inherit = 'donialink.app.admin'

    def _dl_app_admin_sections(self):
        companies = self.env.user.company_ids.ids
        Move = self.env['ecc.owner.move'].sudo()
        CardMove = self.env['ecc.owner.card.move'].sudo()
        expenses = (Move.search_count([('company_id', 'in', companies), ('review_state', '=', 'to_review')])
                    + CardMove.search_count([('company_id', 'in', companies), ('review_state', '=', 'to_review')]))
        differences = self.env['ecc.owner.difference'].sudo().search_count(
            [('box_id.company_id', 'in', companies), ('state', '=', 'pending')])
        receipts = self.env['ecc.receipt'].sudo().search_count(
            [('company_id', 'in', companies), ('state', '=', 'to_review')])
        boxes = self.env['ecc.owner.box'].sudo().search_count([('company_id', 'in', companies)])
        return super()._dl_app_admin_sections() + [{
            'key': 'ecc_cashbox', 'title': _('Cash boxes and receipts'), 'icon': 'cash', 'sequence': 20,
            'numbers': [
                {'label': _('Cash boxes'), 'value': boxes},
                {'label': _('Owner expenses to review'), 'value': expenses, 'warn': True},
                {'label': _('Differences to explain'), 'value': differences, 'warn': True},
                {'label': _('Receipts to review'), 'value': receipts, 'warn': True},
            ],
            'action': 'expense_cash_control_telegram.action_ecc_owner_move_review',
            'button': _('Review'),
        }]
