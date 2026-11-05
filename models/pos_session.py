# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools import float_compare

_logger = logging.getLogger(__name__)


class PosSession(models.Model):
    _inherit = 'pos.session'

    receipt_ids = fields.One2many('ecc.receipt', 'session_id', string='Telegram Receipts')
    cash_out_without_receipt_count = fields.Integer('Cash-Outs Without Receipt',
                                                    compute='_compute_receipt_review_stats')
    receipt_unmatched_count = fields.Integer('Receipts Not Matched', compute='_compute_receipt_review_stats')
    cash_out_receipt_required = fields.Boolean(related='config_id.cash_out_receipt_required')

    # Owner cash box
    owner_move_ids = fields.One2many('ecc.owner.move', 'session_id', string='Owner Collections')
    owner_difference_ids = fields.One2many('ecc.owner.difference', 'session_id', string='Collection Differences')
    owner_collected_amount = fields.Monetary('Collected by Owner', compute='_compute_owner_collection',
                                             currency_field='currency_id')
    owner_remaining_amount = fields.Monetary('Left to Collect', compute='_compute_owner_collection',
                                             currency_field='currency_id',
                                             help='Counted cash of the session not collected by an owner yet.')
    owner_collection_state = fields.Selection([
        ('none', 'Not Collected'), ('partial', 'Partially Collected'), ('collected', 'Collected'),
    ], string='Owner Collection', compute='_compute_owner_collection')
    owner_collection_text = fields.Char('Collection', compute='_compute_owner_collection')
    owner_notified = fields.Boolean(copy=False)

    @api.depends('cash_move_ids.move_type', 'cash_move_ids.receipt_count', 'receipt_ids.state',
                 'receipt_ids.paid_by')
    def _compute_receipt_review_stats(self):
        for session in self:
            session.cash_out_without_receipt_count = len(session.cash_move_ids.filtered(
                lambda m: m.move_type == 'out' and not m.receipt_count))
            session.receipt_unmatched_count = len(session.receipt_ids.filtered(
                lambda r: r.state == 'to_review' and r.paid_by == 'cashier'))

    @api.depends('cash_register_balance_end_real', 'owner_move_ids.amount', 'owner_move_ids.state',
                 'owner_difference_ids.state', 'state')
    def _compute_owner_collection(self):
        for session in self:
            moves = session.owner_move_ids.filtered(lambda m: m.state == 'posted' and m.kind == 'collect')
            collected = sum(moves.mapped('amount'))
            # a POS Cash Out to the owner already left the drawer before counting; a later collection
            # from the safe (statement line) comes out of the counted cash
            from_safe = sum(moves.filtered(lambda m: not m.cash_move_id).mapped('amount'))
            settled = sum(session.owner_difference_ids.filtered(
                lambda d: d.state == 'done' and d.kind == 'collection').mapped('amount'))
            remaining = session.cash_register_balance_end_real - from_safe - settled \
                if session.state == 'closed' else 0.0
            if moves.filtered('cash_move_id'):
                # collected at closing with a POS Cash Out: what stays in the drawer is the float
                remaining = 0.0
            rounding = session.currency_id.rounding or 0.01
            session.owner_collected_amount = collected
            session.owner_remaining_amount = max(remaining, 0.0)
            if float_compare(remaining, 0.0, precision_rounding=rounding) <= 0:
                state = 'collected'
            elif moves or session.owner_difference_ids.filtered(lambda d: d.state == 'pending'):
                state = 'partial'
            else:
                state = 'none'
            session.owner_collection_state = state
            if moves:
                last = moves.sorted('date')[-1]
                when = fields.Datetime.context_timestamp(session, last.date).strftime('%d/%m/%Y')
                owners = ', '.join(sorted(set(moves.box_id.mapped('name'))))
                label = _('Collected by %(owners)s on %(date)s', owners=owners, date=when) if state == 'collected' \
                    else _('Partially collected by %(owners)s', owners=owners)
            else:
                label = dict(self._fields['owner_collection_state']._description_selection(self.env))[state]
            session.owner_collection_text = label

    def _validate_session(self, balancing_account=False, amount_to_balance=0, bank_payment_method_diffs=None):
        result = super()._validate_session(balancing_account, amount_to_balance, bank_payment_method_diffs)
        self.filtered(lambda s: s.state == 'closed' and not s.owner_notified)._notify_owners()
        return result

    def _notify_owners(self):
        """The bot asks each linked owner (partner) of the company: "POS/00412 closed with 1,250,000 cash.
        Collect?". A failure never blocks the closing."""
        Box = self.env['ecc.owner.box'].sudo()
        for session in self:
            session.sudo().owner_notified = True
            boxes = Box.search([('company_id', '=', session.company_id.id), ('is_linked', '=', True),
                                ('notify_session_close', '=', True)]).filtered(
                lambda b: not b.pos_config_ids or session.config_id in b.pos_config_ids)
            amount = session.owner_remaining_amount
            if not boxes or float_compare(amount, 0.0, precision_rounding=session.currency_id.rounding or 0.01) <= 0:
                continue
            text = _('%(session)s closed with %(amount)s cash. Collect?', session=session.name,
                     amount=session.currency_id.format(amount))
            for box in boxes:
                try:
                    box._platform_send('session_closed', text, {'session_id': session.id, 'amount': amount,
                                                                'session': session.name})
                except Exception as e:  # noqa: BLE001 - never block a POS closing for a Telegram message
                    _logger.warning('Owner cash box %s: session %s notification failed: %s', box.name, session.name, e)

    def action_cash_review_done(self):
        for session in self.filtered('config_id.cash_out_receipt_required'):
            if session.cash_out_without_receipt_count or session.receipt_unmatched_count:
                raise UserError(_(
                    'Session %(session)s needs a receipt for every cash-out: %(moves)s cash-out(s) without '
                    'receipt and %(receipts)s receipt(s) not matched.',
                    session=session.name, moves=session.cash_out_without_receipt_count,
                    receipts=session.receipt_unmatched_count))
        return super().action_cash_review_done()

    def action_view_receipts(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('expense_cash_control_telegram.action_ecc_receipt')
        action['domain'] = [('session_id', '=', self.id)]
        action['context'] = {'default_session_id': self.id}
        return action
