# -*- coding: utf-8 -*-
from odoo import api, fields, models


class OwnerCollectionReturn(models.TransientModel):
    """The accountant puts a collection taken by mistake back in the till (Odoo only, not in the bot)."""
    _name = 'ecc.owner.collection.return'
    _description = 'Return Collected Cash to the Till'

    move_id = fields.Many2one('ecc.owner.move', string='Collection', required=True, readonly=True,
                              domain=[('kind', '=', 'collect'), ('state', '=', 'posted')])
    box_id = fields.Many2one(related='move_id.box_id')
    session_id = fields.Many2one(related='move_id.session_id')
    amount = fields.Monetary(related='move_id.amount')
    currency_id = fields.Many2one(related='move_id.currency_id')
    journal_id = fields.Many2one('account.journal', string='Return To', compute='_compute_journal_id')
    reason = fields.Char('Reason', required=True)

    @api.depends('move_id')
    def _compute_journal_id(self):
        for wizard in self:
            wizard.journal_id = wizard.move_id.session_id.cash_journal_id or wizard.move_id.box_id.till_journal_id

    def action_confirm(self):
        self.ensure_one()
        self.move_id._return_to_till(self.reason)
        return {'type': 'ir.actions.act_window_close'}
