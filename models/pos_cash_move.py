# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class PosCashMove(models.Model):
    _inherit = 'pos.cash.move'

    receipt_ids = fields.One2many('ecc.receipt', 'cash_move_id', string='Receipts')
    receipt_count = fields.Integer('Receipt Count', compute='_compute_receipt_count', store=True)
    owner_move_ids = fields.One2many('ecc.owner.move', 'cash_move_id', string='Owner Collection')

    @api.depends('receipt_ids.state')
    def _compute_receipt_count(self):
        # a rejected or duplicate photo proves nothing: the cash-out stays without receipt
        for move in self:
            move.receipt_count = len(move.receipt_ids.filtered(lambda r: r.state not in ('rejected', 'duplicate')))

    @api.model_create_multi
    def create(self, vals_list):
        moves = super().create(vals_list)
        moves._sync_owner_collection()
        return moves

    def action_classify(self):
        result = super().action_classify()
        self._sync_owner_collection()
        return result

    def action_reset(self):
        if self.owner_move_ids.filtered(lambda m: m.state == 'returned'):
            raise UserError(_('This cash-out was returned to the till from the owner box; it cannot be '
                              'classified again.'))
        result = super().action_reset()
        self._sync_owner_collection()
        return result

    def _sync_owner_collection(self):
        """A Cash Out classified with an owner's collection category moves the cash to his box."""
        for move in self:
            box = move.category_id.owner_box_id if move.state == 'classified' and move.move_type == 'out' else False
            current = move.owner_move_ids.filtered(lambda m: m.state == 'posted')
            if move.owner_move_ids.filtered(lambda m: m.state == 'returned'):
                continue   # returned to the till by the accountant: never collected again from here
            if box and not current:
                box._add_move('collect', move.amount_abs,
                              _('Owner collection %(session)s – %(owner)s', session=move.session_id.name or '',
                                owner=box.name),
                              source='pos', session_id=move.session_id.id, cash_move_id=move.id,
                              account_move_id=move.account_move_id.id)
            elif not box and current:
                current.write({'state': 'cancelled'})

    def action_view_receipts(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('expense_cash_control_telegram.action_ecc_receipt')
        action['domain'] = [('cash_move_id', '=', self.id)]
        action['context'] = {}
        return action

    def action_match_receipt(self):
        """Row button in the receipt's suggestions: this cash-out is the one the receipt proves."""
        self.ensure_one()
        receipt = self.env['ecc.receipt'].browse(self.env.context.get('ecc_receipt_id')).exists()
        if not receipt:
            return False
        return receipt._match_cash_move(self)

    def action_pay_vendor_receipt(self):
        """Row button in the receipt's suggestions: this cash-out paid the receipt's vendor."""
        self.ensure_one()
        receipt = self.env['ecc.receipt'].browse(self.env.context.get('ecc_receipt_id')).exists()
        if not receipt:
            return False
        return receipt._pay_vendor_with(self)
