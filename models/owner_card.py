# -*- coding: utf-8 -*-
"""Card box: the bank account the POS card terminal pays into, shared by chosen owners.

Its balance is the balance of its account in the chart of accounts (posted journal items), so anything booked
on that account in Odoo (bank fees, a bank statement, a manual entry) shows in the owner app too.
``ecc.owner.card.move`` tracks who did what with the card:

    sales     card sales of each closed POS session (entered in the bank journal and matched with the
              POS payment, so the bank account follows the card)                                       +
    withdraw  cash taken from the card into an owner's cash box                                        -
    drawing   "Took for me" straight from the card (Owner Drawings, equity)                            -
    expense   a "Paid Now" expense paid by card (photo reviewed in the Receipts inbox)                 -
    deposit   cash from an owner's cash box put on the card                                            +
    adjust    a classified difference (balance checked against the bank app)                          +/-
"""
import logging
from datetime import datetime, time, timedelta

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import float_compare, float_is_zero

_logger = logging.getLogger(__name__)


class OwnerCard(models.Model):
    _name = 'ecc.owner.card'
    _description = 'Owner Card Box'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'company_id, name'

    name = fields.Char('Card', required=True, tracking=True, help='e.g. "Rafidain card" or "Card terminal".')
    company_id = fields.Many2one('res.company', string='Company', required=True, index=True,
                                 default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id')
    active = fields.Boolean(default=True)
    account_id = fields.Many2one(
        'account.account', string='Account', required=True, tracking=True, ondelete='restrict',
        domain="[('account_type', 'in', ('asset_cash', 'asset_current')), ('company_ids', 'in', company_id)]",
        help='The account of the card in the chart of accounts. Its balance in the books is the card balance '
             'shown to the owners.')
    journal_id = fields.Many2one(
        'account.journal', string='Bank Journal', required=True, tracking=True, ondelete='restrict',
        compute='_compute_journal_id', store=True, readonly=False, precompute=True,
        domain="[('type', '=', 'bank'), ('company_id', '=', company_id), ('default_account_id', '=', account_id)]",
        help='The bank journal of the account. Card sales, withdrawals, card expenses and deposits are entered in '
             'it.')
    payment_method_ids = fields.Many2many(
        'pos.payment.method', string='POS Card Methods',
        domain="[('journal_id.type', '=', 'bank'), ('company_id', '=', company_id)]",
        help='The card sales of these POS payment methods are added to the card when a session closes.')
    box_ids = fields.Many2many('ecc.owner.box', 'ecc_owner_card_box_rel', 'card_id', 'box_id', string='Owners',
                               domain="[('company_id', '=', company_id)]", tracking=True,
                               help='These owners see the card in the owner app and can withdraw, spend and '
                                    'deposit with it.')
    feed_from = fields.Date('Card Sales From', required=True, default=fields.Date.context_today,
                            help='Card sales of the sessions closed from this day are added to the card.')

    move_ids = fields.One2many('ecc.owner.card.move', 'card_id', string='Movements')
    difference_ids = fields.One2many('ecc.owner.difference', 'card_id', string='Differences')
    balance = fields.Monetary('Balance', compute='_compute_balance',
                              help='Balance of the account in the books (posted journal items).')
    difference_pending_count = fields.Integer('Differences to Explain', compute='_compute_balance')

    _sql_constraints = [
        ('account_unique', 'unique(account_id)', 'This account is already used by another card.'),
    ]

    # ------------------------------------------------------------------
    # Compute
    # ------------------------------------------------------------------

    def _account_lines_domain(self):
        self.ensure_one()
        return [('account_id', '=', self.account_id.id), ('company_id', '=', self.company_id.id),
                ('parent_state', '=', 'posted')]

    @api.depends('account_id', 'move_ids.amount', 'move_ids.state', 'difference_ids.state')
    def _compute_balance(self):
        Line = self.env['account.move.line'].sudo()
        for card in self:
            if card.account_id and card.company_id:
                card.balance = Line._read_group(card._account_lines_domain(), [], ['balance:sum'])[0][0] or 0.0
            else:
                card.balance = 0.0
            card.difference_pending_count = len(card.difference_ids.filtered(lambda d: d.state == 'pending'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('account_id') and vals.get('journal_id'):
                vals['account_id'] = self.env['account.journal'].browse(vals['journal_id']).default_account_id.id
        return super().create(vals_list)

    @api.depends('account_id', 'company_id')
    def _compute_journal_id(self):
        for card in self:
            if card.account_id and card.journal_id.default_account_id != card.account_id:
                card.journal_id = self.env['account.journal'].search([
                    ('type', '=', 'bank'), ('default_account_id', '=', card.account_id.id),
                    ('company_id', '=', (card.company_id or self.env.company).id)], limit=1)

    @api.constrains('account_id', 'journal_id')
    def _check_journal_account(self):
        for card in self:
            if card.journal_id.default_account_id != card.account_id:
                raise ValidationError(_(
                    'The card %(card)s: the bank journal %(journal)s must use the account %(account)s, else the '
                    'card movements would not change the card balance.', card=card.name,
                    journal=card.journal_id.display_name, account=card.account_id.display_name))

    @api.onchange('journal_id')
    def _onchange_journal_id(self):
        if self.journal_id and self.journal_id.default_account_id:
            self.account_id = self.journal_id.default_account_id
        if self.journal_id and not self.payment_method_ids:
            self.payment_method_ids = self.env['pos.payment.method'].search(
                [('journal_id', '=', self.journal_id.id)])

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _check_owner(self, box):
        self.ensure_one()
        if not box or box not in self.box_ids or not self.active:
            raise AccessError(_('The card %s is not shared with this owner.', self.name))

    def _check_amount(self, amount):
        if float_compare(amount or 0.0, 0.0, precision_rounding=self.currency_id.rounding) <= 0:
            raise UserError(_('The amount must be positive.'))

    def _statement_line(self, amount, label, counterpart_account, date=None):
        """Money in (+) or out (-) of the card's bank journal, against ``counterpart_account``."""
        self.ensure_one()
        return self.env['account.bank.statement.line'].sudo().with_company(self.company_id).create({
            'journal_id': self.journal_id.id,
            'amount': amount,
            'payment_ref': label,
            'date': date or fields.Date.context_today(self),
            'counterpart_account_id': counterpart_account.id,
        })

    def _add_move(self, kind, amount, name, box=None, source='odoo', **links):
        self.ensure_one()
        move = self.env['ecc.owner.card.move'].sudo().create(dict(
            card_id=self.id, box_id=box.id if box else False, kind=kind, amount=amount, name=name,
            source=source, **links))
        self._notify_move(move)
        return move

    def _notify_move(self, move):
        """Notification to the owners of the card, except the one who made the movement."""
        self.ensure_one()
        for owner in (self.box_ids - move.box_id).filtered(
                lambda b: b.app_user_id or b.telegram_user_id or b.platform_enabled):
            card = self.with_context(lang=owner._app_lang()).sudo()
            card.invalidate_recordset(['balance'])
            sign = '+' if move.amount > 0 else '−'
            body = '%s%s · %s' % (sign, card.currency_id.format(abs(move.amount)), move.name)
            if move.box_id:
                body = '%s: %s' % (move.box_id.name, body)
            title = _('%(card)s: %(balance)s', card=card.name, balance=card.currency_id.format(card.balance))
            owner._owner_notify(
                'card_sales' if move.kind == 'sales' else 'card_move', '%s\n%s' % (title, body), title, body=body,
                route='bankcard', card=card, tag='card-move-%s' % move.id,
                data={'card_move_id': move.id, 'move_kind': move.kind, 'amount': move.amount,
                      'balance': card.balance, 'session_id': move.session_id.id or None})

    # ------------------------------------------------------------------
    # Card sales from the POS
    # ------------------------------------------------------------------

    def _session_card_lines(self, session, methods):
        """Journal items of ``session`` on the outstanding receipts account of the card ``methods``: what the
        card terminal really paid (Odoo already added the counted difference to them)."""
        Line = self.env['account.move.line'].sudo()
        payments = self.env['account.payment'].sudo().search(
            [('pos_session_id', '=', session.id), ('pos_payment_method_id', 'in', methods.ids)])
        # without an outstanding account (Odoo without full accounting) the payment goes straight to the bank
        accounts = payments.outstanding_account_id | methods.outstanding_account_id \
            | methods.journal_id.default_account_id
        if not accounts:
            return Line
        return Line.search([
            ('account_id', 'in', accounts.ids),
            ('parent_state', '=', 'posted'),
            '|', ('move_id', 'in', payments.move_id.ids),
            '&', ('journal_id', 'in', methods.journal_id.ids), ('move_id.ref', 'ilike', '(%s)' % session.name),
        ])

    def _feed_session(self, session):
        """Add the card sales of a closed session to the card. The amount is entered in the bank journal and
        matched with the POS payment, so it is never counted twice by a later bank reconciliation."""
        self.ensure_one()
        Move = self.env['ecc.owner.card.move']
        if self.move_ids.filtered(lambda m: m.kind == 'sales' and m.session_id == session and m.state == 'posted'):
            return Move
        methods = self.payment_method_ids & session.payment_method_ids
        if not methods or session.state != 'closed':
            return Move
        lines = self._session_card_lines(session, methods)
        rounding = self.currency_id.rounding
        amount = sum(lines.mapped('balance'))
        if float_is_zero(amount, precision_rounding=rounding):
            return Move
        label = _('Card sales %(session)s – %(card)s', session=session.name, card=self.name)
        date = fields.Date.context_today(self, session.stop_at) if session.stop_at else None
        st_lines = self.env['account.bank.statement.line']
        bank_accounts = methods.journal_id.default_account_id
        for account in lines.account_id - bank_accounts:
            open_lines = lines.filtered(lambda l: l.account_id == account and not l.reconciled)
            open_amount = sum(open_lines.mapped('amount_residual'))
            if float_is_zero(open_amount, precision_rounding=rounding):
                continue   # already matched with a bank statement by the accountant
            st_line = self._statement_line(open_amount, label, account, date=date)
            _liquidity, _suspense, other = st_line._seek_for_lines()
            (other | open_lines).reconcile()
            st_lines |= st_line
        return self._add_move('sales', amount, label, source='pos', session_id=session.id,
                              date=session.stop_at or fields.Datetime.now(),
                              statement_line_id=st_lines[:1].id, account_move_id=st_lines[:1].move_id.id)

    @api.model
    def _feed_sessions(self, sessions):
        moves = self.env['ecc.owner.card.move']
        for card in self.sudo().search([('company_id', 'in', sessions.company_id.ids)]):
            for session in sessions.filtered(lambda s: s.company_id == card.company_id and s.stop_at
                                             and fields.Date.context_today(card, s.stop_at) >= card.feed_from):
                moves |= card._feed_session(session)
        return moves

    def _sessions_to_feed(self, days=None):
        """Closed sessions with card sales not added yet (``days``: only those closed in the last days)."""
        self.ensure_one()
        start = datetime.combine(self.feed_from, time.min) - timedelta(days=1)
        if days:
            start = max(start, fields.Datetime.now() - timedelta(days=days))
        sessions = self.env['pos.session'].sudo().search([
            ('company_id', '=', self.company_id.id), ('state', '=', 'closed'), ('stop_at', '>=', start),
            ('config_id.payment_method_ids', 'in', self.payment_method_ids.ids)])
        fed = self.move_ids.filtered(lambda m: m.kind == 'sales' and m.state == 'posted').session_id
        return sessions - fed

    def action_feed_sales(self):
        moves = self.env['ecc.owner.card.move']
        for card in self:
            moves |= self._feed_sessions(card._sessions_to_feed()).filtered(lambda m: m.card_id == card)
        return self.env['cash.difference.reconciliation']._notify(
            _('Card Sales'), _('%s session(s) added to the card.', len(moves)) if moves
            else _('No new card sales.'), 'success' if moves else 'info')

    @api.model
    def _cron_feed_sales(self):
        for card in self.search([]):
            try:
                with self.env.cr.savepoint():
                    self._feed_sessions(card._sessions_to_feed(days=7))
            except Exception as e:  # noqa: BLE001 - one card must not stop the others
                _logger.warning('Card box %s: card sales not added: %s', card.name, e)

    # ------------------------------------------------------------------
    # Movements (owner app and Odoo screens)
    # ------------------------------------------------------------------

    def _withdraw(self, box, amount, target='box', note=None, source='odoo'):
        """Cash taken from the card: into the owner's cash box ("box") or for himself ("took")."""
        self.ensure_one()
        self._check_owner(box)
        self._check_amount(amount)
        if target == 'took':
            label = _('Took for me from %(card)s – %(owner)s', card=self.name, owner=box.name)
            counterpart = box.drawings_account_id
        else:
            label = _('Cash from %(card)s – %(owner)s', card=self.name, owner=box.name)
            counterpart = box._cash_account()
        if note:
            label += ' · %s' % note
        st_line = self._statement_line(-amount, label, counterpart)
        owner_move = self.env['ecc.owner.move']
        if target != 'took':
            owner_move = box._add_move('from_card', amount, label, source=source, card_id=self.id,
                                       account_move_id=st_line.move_id.id, statement_line_id=st_line.id)
        return self._add_move('drawing' if target == 'took' else 'withdraw', -amount, label, box=box, source=source,
                              statement_line_id=st_line.id, account_move_id=st_line.move_id.id,
                              owner_move_id=owner_move.id)

    def _deposit(self, box, amount, note=None, source='odoo'):
        """Cash of the owner's box put on the card."""
        self.ensure_one()
        self._check_owner(box)
        self._check_amount(amount)
        label = _('Owner deposit to %(card)s – %(owner)s', card=self.name, owner=box.name)
        if note:
            label += ' · %s' % note
        st_line = self._statement_line(amount, label, box._cash_account())
        owner_move = box._add_move('deposit', -amount, label, source=source, deposit_target='card', card_id=self.id,
                                   account_move_id=st_line.move_id.id, statement_line_id=st_line.id)
        card_move = self._add_move('deposit', amount, label, box=box, source=source, statement_line_id=st_line.id,
                                   account_move_id=st_line.move_id.id, owner_move_id=owner_move.id)
        return owner_move, card_move

    def _record_expense(self, box, amount, category, note=None, photos=(), source='odoo'):
        """Expense paid by card: a "Paid Now" expense from the card's bank journal, final after the accountant's
        review in the Receipts inbox."""
        self.ensure_one()
        self._check_owner(box)
        expense, receipt = box._create_owner_expense(amount, category, note=note, photos=photos, source=source,
                                                     journal=self.journal_id, card=self)
        move = self._add_move('expense', -amount, expense.name, box=box, source=source, expense_id=expense.id,
                              receipt_id=receipt.id, account_move_id=expense.move_id.id)
        return move, receipt

    def _record_count(self, box, counted):
        """Balance checked in the bank app: a difference goes to the accountant to explain."""
        self.ensure_one()
        self._check_owner(box)
        difference = counted - self.balance
        if float_is_zero(difference, precision_rounding=self.currency_id.rounding):
            return self.env['ecc.owner.difference']
        return self.env['ecc.owner.difference'].sudo().create({
            'box_id': box.id, 'card_id': self.id, 'kind': 'card_count', 'amount': difference,
            'counted': counted, 'expected': self.balance,
        })

    # ------------------------------------------------------------------
    # App data
    # ------------------------------------------------------------------

    def _api_summary(self):
        self.ensure_one()
        card = self.sudo()
        card.invalidate_recordset(['balance'])
        return {
            'account': card.account_id.display_name,
            'card_id': card.id,
            'name': card.name,
            'bank': card.journal_id.name,
            'balance': card.balance,
            'balance_text': card.currency_id.format(card.balance),
        }

    def _api_moves(self, limit=30):
        """History of the card = journal items of its account (newest first), named after the card movement
        when the owner app or the POS made it, else after the journal entry (bank fees, statements...)."""
        self.ensure_one()
        card = self.sudo()
        card.invalidate_recordset(['balance'])
        lines = self.env['account.move.line'].sudo().search(card._account_lines_domain(),
                                                             order='date desc, id desc', limit=limit)
        card_moves = self.env['ecc.owner.card.move'].sudo().search(
            [('card_id', '=', card.id), ('account_move_id', 'in', lines.move_id.ids)])
        by_entry = {m.account_move_id.id: m for m in card_moves}
        bank_label = _('Bank Entry')
        running = card.balance
        currency = card.currency_id
        rows = []
        for line in lines:
            move = by_entry.get(line.move_id.id)
            entry = line.move_id
            rows.append({
                'id': line.id, 'local_date': line.date.strftime('%d/%m/%Y'),
                'type': move.kind if move else 'bank',
                'type_label': move._kind_label() if move else bank_label,
                'description': move.name if move else (line.name or entry.ref or entry.name),
                'owner': move.box_id.name if move else '', 'entry': entry.name,
                'amount': line.balance, 'amount_text': currency.format(line.balance),
                'balance_after': running, 'balance_after_text': currency.format(running),
                'review': move.receipt_id.state if move and move.receipt_id else False,
            })
            running -= line.balance
        return rows

    # ------------------------------------------------------------------
    # Odoo screens
    # ------------------------------------------------------------------

    def action_view_moves(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('Movements of %s', self.name),
                'res_model': 'ecc.owner.card.move', 'views': [(False, 'list'), (False, 'form')],
                'domain': [('card_id', '=', self.id)], 'context': {'default_card_id': self.id}}

    def action_view_differences(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('Differences of %s', self.name),
                'res_model': 'ecc.owner.difference', 'views': [(False, 'list')],
                'domain': [('card_id', '=', self.id)]}


class OwnerCardMove(models.Model):
    _name = 'ecc.owner.card.move'
    _description = 'Owner Card Movement'
    _order = 'date desc, id desc'

    card_id = fields.Many2one('ecc.owner.card', string='Card', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='card_id.company_id', store=True, index=True)
    currency_id = fields.Many2one(related='card_id.currency_id')
    box_id = fields.Many2one('ecc.owner.box', string='Owner', ondelete='set null', index='btree_not_null',
                             help='The owner who made the movement.')
    date = fields.Datetime(required=True, default=fields.Datetime.now, index=True)
    kind = fields.Selection([
        ('sales', 'Card Sales'),
        ('withdraw', 'Cash Withdrawal'),
        ('drawing', 'Took for Me'),
        ('expense', 'Expense'),
        ('deposit', 'Deposit'),
        ('adjust', 'Adjustment'),
    ], string='Type', required=True, index=True)
    name = fields.Char('Description', required=True)
    amount = fields.Monetary('Amount', required=True, help='Effect on the card balance: + in, − out.')
    state = fields.Selection([('posted', 'Posted'), ('cancelled', 'Cancelled')], default='posted', required=True,
                             index=True)
    source = fields.Selection([('pos', 'POS'), ('odoo', 'Odoo'), ('app', 'Owner App'), ('platform', 'DoniaLink App'),
                               ('telegram', 'Telegram')],
                              default='odoo')
    session_id = fields.Many2one('pos.session', string='POS Session', ondelete='set null', index='btree_not_null')
    expense_id = fields.Many2one('expense.express', string='Expense', ondelete='cascade', index='btree_not_null')
    receipt_id = fields.Many2one('ecc.receipt', string='Receipt', ondelete='set null')
    difference_id = fields.Many2one('ecc.owner.difference', ondelete='cascade')
    owner_move_id = fields.Many2one('ecc.owner.move', string='Owner Box Movement', ondelete='set null')
    statement_line_id = fields.Many2one('account.bank.statement.line', ondelete='set null')
    account_move_id = fields.Many2one('account.move', string='Journal Entry', ondelete='set null')
    app_request_uid = fields.Char('App Request', copy=False, index='btree_not_null', readonly=True)

    _sql_constraints = [
        ('app_request_uid_unique', 'unique(card_id, app_request_uid)', 'This app action was already recorded.'),
    ]

    def _kind_label(self):
        return dict(self._fields['kind']._description_selection(self.env))[self.kind]

    def action_open_entry(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'account.move', 'res_id': self.account_move_id.id,
                'views': [(False, 'form')]}
