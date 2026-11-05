# -*- coding: utf-8 -*-
"""Owner cash box: the cash a café owner (or each partner) holds after collecting closed POS sessions.

The owner talks to the DoniaLink bot in a private chat (run by the DoniaLink Platform, which calls the
``owner_*`` agent tools). Every change of his cash is an ``ecc.owner.move``; his balance is their sum,
so it is computed by Odoo, never typed:

    collect   POS cash -> owner box (a POS Cash Out with his collection category, or later from the bot)  +
    expense   a "Paid Now" expense from his box (photo reviewed in the Receipts inbox)                     -
    drawing   "Took for me": owner box -> Owner Drawings (equity)                                           -
    deposit   owner box -> bank (internal transfer account) or back to the till (POS cash journal)          -
    adjust    a classified difference (count of his cash)                                                  +/-

A negative balance means the business owes him the money.
"""
import secrets
from datetime import datetime, time, timedelta

import pytz
from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, modules, Command, _
from odoo.exceptions import UserError
from odoo.tools import float_compare, float_is_zero

WEEKDAYS = [('0', 'Monday'), ('1', 'Tuesday'), ('2', 'Wednesday'), ('3', 'Thursday'),
            ('4', 'Friday'), ('5', 'Saturday'), ('6', 'Sunday')]
LINK_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'


class OwnerNotLinked(Exception):
    """The Telegram user is not the owner linked to this box."""


class OwnerBox(models.Model):
    _name = 'ecc.owner.box'
    _description = 'Owner Cash Box'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'company_id, name'

    name = fields.Char('Owner', required=True, tracking=True, help='Owner or partner holding this cash.')
    company_id = fields.Many2one('res.company', string='Company', required=True, index=True,
                                 default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id')
    active = fields.Boolean(default=True)
    journal_id = fields.Many2one('account.journal', string='Cash Journal', readonly=True, ondelete='restrict',
                                 help='Dedicated cash journal of the box, e.g. "Owner Cash – Ali". Created with the box.')
    account_id = fields.Many2one(related='journal_id.default_account_id', string='Cash Account')
    drawings_account_id = fields.Many2one(
        'account.account', string='Owner Drawings Account', required=True, tracking=True,
        default=lambda self: self._default_drawings_account(),
        domain="[('account_type', 'in', ('equity', 'equity_unaffected'))]",
        help='Equity account receiving "Took for me" (personal withdrawals). Never an expense.')
    bank_journal_id = fields.Many2one('account.journal', string='Deposit Bank', tracking=True,
                                      domain="[('type', '=', 'bank'), ('company_id', '=', company_id)]",
                                      help='Bank where "Deposit to bank" goes (through the internal transfer account).')
    till_journal_id = fields.Many2one('account.journal', string='Deposit Till', tracking=True,
                                      domain="[('type', '=', 'cash'), ('company_id', '=', company_id)]",
                                      help='POS cash journal where "Deposit back to the till" goes.')
    collection_category_id = fields.Many2one(
        'expense.category', string='POS Collection Category', readonly=True,
        help='A POS Cash Out with this category ("Owner collection – Ali") moves the cash to this box.')
    pos_config_ids = fields.Many2many('pos.config', string='Points of Sale',
                                      domain="[('company_id', '=', company_id)]",
                                      help='Sessions of these POS can be collected. Empty: every POS of the company.')
    collect_from = fields.Date('Collect Sessions From', required=True, default=fields.Date.context_today,
                               help='Sessions closed before this day are not offered for collection.')

    # Telegram
    telegram_user_id = fields.Char('Telegram User', readonly=True, copy=False, index=True, tracking=True)
    telegram_name = fields.Char('Telegram Name', readonly=True, copy=False)
    link_code = fields.Char('Link Code', readonly=True, copy=False, index=True)
    link_url = fields.Char('Link', readonly=True, copy=False)
    is_linked = fields.Boolean('Linked', compute='_compute_is_linked', store=True)
    notify_session_close = fields.Boolean('Notify on Session Close', default=True,
                                          help='The bot asks "POS/00412 closed with 1,250,000 cash. Collect?"')
    statement_frequency = fields.Selection([
        ('weekly', 'Weekly'), ('monthly', 'Monthly'), ('none', 'Never'),
    ], string='Statement', default='weekly', required=True, tracking=True)
    statement_weekday = fields.Selection(WEEKDAYS, string='Statement Day', default='4',
                                         help='Weekly statement: sent on this day for the 7 days before.')

    move_ids = fields.One2many('ecc.owner.move', 'box_id', string='Movements')
    statement_ids = fields.One2many('ecc.owner.statement', 'box_id', string='Statements')
    difference_ids = fields.One2many('ecc.owner.difference', 'box_id', string='Differences')
    receipt_ids = fields.One2many('ecc.receipt', 'owner_box_id', string='Expense Receipts')

    balance = fields.Monetary('Balance', compute='_compute_balance',
                              help='Collected − expenses − took for me − deposits ± adjustments. '
                                   'Negative: the business owes the owner.')
    account_balance = fields.Monetary('Account Balance', compute='_compute_balance',
                                      help='Balance of the cash account in the books, for checking.')
    uncollected_session_count = fields.Integer('Sessions Not Collected', compute='_compute_counters')
    uncollected_amount = fields.Monetary('Cash Not Collected', compute='_compute_counters')
    receipt_to_review_count = fields.Integer('Expenses to Review', compute='_compute_counters')
    difference_pending_count = fields.Integer('Differences to Explain', compute='_compute_counters')
    last_statement_id = fields.Many2one('ecc.owner.statement', string='Last Statement',
                                        compute='_compute_counters')
    last_statement_state = fields.Selection([
        ('draft', 'Not Sent'), ('sent', 'Waiting for Owner'), ('confirmed', 'Confirmed'), ('disputed', 'Disputed'),
    ], string='Last Statement Status', compute='_compute_counters')

    _sql_constraints = [
        ('link_code_unique', 'UNIQUE(link_code)', 'This link code is already used.'),
    ]

    @api.model
    def _default_drawings_account(self):
        Account = self.env['account.account']
        domain = [('account_type', '=', 'equity'), ('company_ids', 'in', self.env.company.id)]
        return Account.search(domain + [('name', 'ilike', 'drawing')], limit=1) or Account.search(domain, limit=1)

    # ------------------------------------------------------------------
    # Compute
    # ------------------------------------------------------------------

    @api.depends('telegram_user_id')
    def _compute_is_linked(self):
        for box in self:
            box.is_linked = bool(box.telegram_user_id)

    @api.depends('move_ids.amount', 'move_ids.state')
    def _compute_balance(self):
        data = dict(self.env['ecc.owner.move'].sudo()._read_group(
            [('box_id', 'in', self.ids), ('state', '=', 'posted')], ['box_id'], ['amount:sum']))
        for box in self:
            box.balance = data.get(box, 0.0)
            account = box.journal_id.default_account_id
            if account:
                lines = self.env['account.move.line'].sudo()._read_group(
                    [('account_id', '=', account.id), ('parent_state', '=', 'posted')], [], ['balance:sum'])
                box.account_balance = lines[0][0] or 0.0
            else:
                box.account_balance = 0.0

    def _compute_counters(self):
        Receipt = self.env['ecc.receipt']
        for box in self:
            sessions = box._uncollected_sessions() if box.id else self.env['pos.session']
            box.uncollected_session_count = len(sessions)
            box.uncollected_amount = sum(sessions.mapped('owner_remaining_amount'))
            box.receipt_to_review_count = Receipt.search_count(
                [('owner_box_id', '=', box.id), ('state', '=', 'to_review')]) if box.id else 0
            box.difference_pending_count = len(box.difference_ids.filtered(lambda d: d.state == 'pending'))
            box.last_statement_id = box.statement_ids[:1]
            box.last_statement_state = box.last_statement_id.state

    # ------------------------------------------------------------------
    # ORM
    # ------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('journal_id'):
                company = self.env['res.company'].browse(vals.get('company_id') or self.env.company.id)
                vals['journal_id'] = self._create_journal(vals['name'], company).id
        boxes = super().create(vals_list)
        for box in boxes:
            box.collection_category_id = self.env['expense.category'].sudo().create({
                'name': _('Owner collection – %s', box.name),
                'code': 'OWNER-%s' % box.id,
                'account_id': box.journal_id.default_account_id.id,
                'company_id': box.company_id.id,
                'available_in_pos': True,
                'pos_cash_type': 'out',
                'owner_box_id': box.id,
            })
        return boxes

    @api.model
    def _create_journal(self, name, company):
        Journal = self.env['account.journal'].sudo()
        code = 'OWN'
        for i in range(1, 1000):
            code = 'OWN%s' % i
            if not Journal.with_context(active_test=False).search_count(
                    [('code', '=', code), ('company_id', '=', company.id)]):
                break
        return Journal.create({
            'name': _('Owner Cash – %s', name),
            'type': 'cash',
            'code': code,
            'company_id': company.id,
        })

    def write(self, vals):
        result = super().write(vals)
        if 'name' in vals:
            for box in self.filtered('collection_category_id'):
                box.collection_category_id.sudo().name = _('Owner collection – %s', box.name)
        return result

    # ------------------------------------------------------------------
    # Sessions
    # ------------------------------------------------------------------

    def _session_domain(self):
        self.ensure_one()
        domain = [('company_id', '=', self.company_id.id), ('state', '=', 'closed'),
                  ('cash_journal_id', '!=', False),
                  ('stop_at', '>=', datetime.combine(self.collect_from, time.min))]
        if self.pos_config_ids:
            domain.append(('config_id', 'in', self.pos_config_ids.ids))
        return domain

    def _uncollected_sessions(self):
        self.ensure_one()
        sessions = self.env['pos.session'].sudo().search(self._session_domain(), order='stop_at desc')
        return sessions.filtered(lambda s: s.owner_collection_state != 'collected')

    # ------------------------------------------------------------------
    # Movements (called by the agent tools and the Odoo screens)
    # ------------------------------------------------------------------

    def _check_amount(self, amount):
        if float_compare(amount or 0.0, 0.0, precision_rounding=self.currency_id.rounding) <= 0:
            raise UserError(_('The amount must be positive.'))

    def _cash_account(self):
        account = self.journal_id.default_account_id
        if not account:
            raise UserError(_('The journal %s has no cash account.', self.journal_id.display_name))
        return account

    def _post_entry(self, label, debit_account, credit_account, amount):
        """A posted entry in the box journal: ``amount`` from ``credit_account`` to ``debit_account``."""
        move = self.env['account.move'].sudo().with_company(self.company_id).create({
            'journal_id': self.journal_id.id,
            'date': fields.Date.context_today(self),
            'ref': label,
            'line_ids': [
                Command.create({'name': label, 'account_id': debit_account.id, 'debit': amount}),
                Command.create({'name': label, 'account_id': credit_account.id, 'credit': amount}),
            ],
        })
        move.action_post()
        return move

    def _till_statement_line(self, journal, amount, label):
        """Cash in (+) or out (-) of a POS cash journal, against the box account."""
        return self.env['account.bank.statement.line'].sudo().with_company(self.company_id).create({
            'journal_id': journal.id,
            'amount': amount,
            'payment_ref': label,
            'date': fields.Date.context_today(self),
            'counterpart_account_id': self._cash_account().id,
        })

    def _add_move(self, kind, amount, name, source='odoo', **links):
        return self.env['ecc.owner.move'].sudo().create(dict(
            box_id=self.id, kind=kind, amount=amount, name=name, source=source, **links))

    def _collect_session(self, session, amount=None, source='telegram'):
        """Owner took the cash of a closed session from the safe. ``amount`` None = all that is left.
        A smaller amount ("Other amount") opens a difference for the accountant (left in till, loss...)."""
        self.ensure_one()
        session.ensure_one()
        if not self.env['pos.session'].sudo().search_count(self._session_domain() + [('id', '=', session.id)]):
            raise UserError(_('Session %s cannot be collected into this box.', session.name))
        rounding = self.currency_id.rounding
        remaining = session.owner_remaining_amount
        if float_compare(remaining, 0.0, precision_rounding=rounding) <= 0:
            raise UserError(_('Session %s was already collected.', session.name))
        amount = remaining if amount is None else amount
        self._check_amount(amount)
        if float_compare(amount, remaining, precision_rounding=rounding) > 0:
            raise UserError(_('Session %(session)s has only %(left)s left to collect.',
                              session=session.name, left=self.currency_id.format(remaining)))
        label = _('Owner collection %(session)s – %(owner)s', session=session.name, owner=self.name)
        st_line = self._till_statement_line(session.cash_journal_id, -amount, label)
        move = self._add_move('collect', amount, label, source=source, session_id=session.id,
                              account_move_id=st_line.move_id.id, statement_line_id=st_line.id)
        Difference = self.env['ecc.owner.difference'].sudo()
        session.owner_difference_ids.filtered(lambda d: d.state == 'pending' and d.kind == 'collection').write(
            {'state': 'cancelled'})
        left = remaining - amount
        if not float_is_zero(left, precision_rounding=rounding):
            Difference.create({
                'box_id': self.id, 'kind': 'collection', 'session_id': session.id, 'amount': left,
                'note': _('Collected %(amount)s of %(total)s.', amount=self.currency_id.format(amount),
                          total=self.currency_id.format(remaining)),
            })
        return move

    def _record_expense(self, amount, category, note=None, photos=(), chat_id=None, message_id=None,
                        sender=None, source='telegram'):
        """Owner paid a business expense from his cash: a "Paid Now" expense from the box, final after the
        accountant's review in the Receipts inbox."""
        self.ensure_one()
        self._check_amount(amount)
        if not category.account_id:
            raise UserError(_('The category "%s" has no account.', category.name))
        expense = self.env['expense.express'].sudo().with_company(self.company_id).create({
            'name': (note or '').strip()[:120] or category.name,
            'amount': amount,
            'category_id': category.id,
            'payment_mode': 'paid',
            'journal_id': self.journal_id.id,
            'company_id': self.company_id.id,
            'notes': _('Paid by %s from his cash (Telegram).', self.name),
        })
        receipt = self.env['ecc.receipt'].sudo().with_company(self.company_id).create({
            'company_id': self.company_id.id,
            'paid_by': 'owner',
            'owner_box_id': self.id,
            'sender_id': sender.id if sender else False,
            'chat_id': str(chat_id) if chat_id else False,
            'message_id': message_id or 0,
            'note': note or False,
            'amount': amount,
            'category_id': category.id,
            'expense_id': expense.id,
        })
        for photo in photos:
            receipt._add_photo(photo['content'], photo.get('filename'), photo.get('mimetype'),
                               photo.get('message_id'), photo.get('file_unique_id'))
        copies = receipt._copy_photos(expense)
        if copies:
            expense.write({'attachment_ids': [Command.link(a.id) for a in copies]})
        move = self._add_move('expense', -amount, expense.name, source=source, expense_id=expense.id,
                              receipt_id=receipt.id, account_move_id=expense.move_id.id)
        return move, receipt

    def _record_drawing(self, amount, note=None, source='telegram'):
        """Took for me: personal withdrawal to Owner Drawings (equity), never an expense."""
        self.ensure_one()
        self._check_amount(amount)
        label = _('Took for me – %s', self.name) + (' · %s' % note if note else '')
        entry = self._post_entry(label, self.drawings_account_id, self._cash_account(), amount)
        return self._add_move('drawing', -amount, label, source=source, account_move_id=entry.id)

    def _record_deposit(self, amount, target, note=None, source='telegram'):
        """Deposit to the bank (through the internal transfer account, matched later with the bank statement)
        or back to the till (a cash in of the POS cash journal)."""
        self.ensure_one()
        self._check_amount(amount)
        if target == 'till':
            journal = self.till_journal_id
            if not journal:
                raise UserError(_('No till is set on the cash box of %s.', self.name))
            label = _('Owner deposit to %(journal)s – %(owner)s', journal=journal.name, owner=self.name)
            st_line = self._till_statement_line(journal, amount, label)
            return self._add_move('deposit', -amount, label, source=source, deposit_target='till',
                                  account_move_id=st_line.move_id.id, statement_line_id=st_line.id)
        transfer = self.company_id.transfer_account_id
        if not transfer:
            raise UserError(_('Set the internal transfer account of the company first (Accounting settings).'))
        label = _('Owner deposit to %(bank)s – %(owner)s', bank=self.bank_journal_id.name or _('bank'),
                  owner=self.name)
        if note:
            label += ' · %s' % note
        entry = self._post_entry(label, transfer, self._cash_account(), amount)
        return self._add_move('deposit', -amount, label, source=source, deposit_target='bank',
                              account_move_id=entry.id)

    def _record_count(self, counted):
        """Count my cash: a difference with the computed balance goes to the accountant to explain."""
        self.ensure_one()
        difference = counted - self.balance
        if float_is_zero(difference, precision_rounding=self.currency_id.rounding):
            return self.env['ecc.owner.difference']
        return self.env['ecc.owner.difference'].sudo().create({
            'box_id': self.id, 'kind': 'count', 'amount': difference, 'counted': counted,
            'expected': self.balance,
        })

    # ------------------------------------------------------------------
    # Statements
    # ------------------------------------------------------------------

    def _utc_bounds(self, date_from, date_to):
        zone = pytz.timezone(self.env['donialink.agent.tools']._business_tz() or 'UTC')

        def to_utc(day):
            return zone.localize(datetime.combine(day, time.min)).astimezone(pytz.utc).replace(tzinfo=None)
        return to_utc(date_from), to_utc(date_to + timedelta(days=1))

    def _period_figures(self, date_from, date_to):
        """Opening, flows and closing of [date_from, date_to] (local days)."""
        self.ensure_one()
        start, stop = self._utc_bounds(date_from, date_to)
        Move = self.env['ecc.owner.move'].sudo()
        before = Move.search([('box_id', '=', self.id), ('state', '=', 'posted'), ('date', '<', start)])
        moves = Move.search([('box_id', '=', self.id), ('state', '=', 'posted'),
                             ('date', '>=', start), ('date', '<', stop)])

        def total(kind):
            return sum(moves.filtered(lambda m: m.kind == kind).mapped('amount'))
        opening = sum(before.mapped('amount'))
        return {
            'opening': opening,
            'collected': total('collect'),
            'spent': -total('expense'),
            'took': -total('drawing'),
            'deposited': -total('deposit'),
            'adjusted': total('adjust'),
            'closing': opening + sum(moves.mapped('amount')),
        }

    def _statement_due(self, today):
        """(date_from, date_to) of the statement due today, or None."""
        self.ensure_one()
        if self.statement_frequency == 'weekly' and str(today.weekday()) == (self.statement_weekday or '4'):
            period = (today - timedelta(days=7), today - timedelta(days=1))
        elif self.statement_frequency == 'monthly' and today.day == 1:
            period = (today - relativedelta(months=1), today - timedelta(days=1))
        else:
            return None
        if self.statement_ids.filtered(lambda s: s.date_to == period[1]):
            return None
        return period

    def _create_statement(self, date_from, date_to):
        self.ensure_one()
        return self.env['ecc.owner.statement'].sudo().create(dict(
            self._period_figures(date_from, date_to), box_id=self.id, date_from=date_from, date_to=date_to))

    @api.model
    def _cron_owner_statements(self):
        for box in self.search([('is_linked', '=', True), ('statement_frequency', '!=', 'none')]):
            period = box._statement_due(fields.Date.context_today(box))
            if not period:
                continue
            statement = box._create_statement(*period)
            try:
                statement._send()
            except UserError as e:
                # one box the platform refuses (not linked there, bot off) must not stop the others;
                # the statement stays "Not Sent" and can be sent again from Odoo
                statement.message_post(body=_('Not sent: %s', e.args[0] if e.args else e))
            if not modules.module.current_test:
                self.env.cr.commit()   # each box's statement is kept even if a later one fails

    # ------------------------------------------------------------------
    # Telegram
    # ------------------------------------------------------------------

    def _check_telegram_user(self, telegram_user_id):
        self.ensure_one()
        if not self.active or not self.telegram_user_id or str(telegram_user_id) != self.telegram_user_id:
            raise OwnerNotLinked()

    def _platform_send(self, kind, text, data=None):
        """Message to the owner's private chat through the DoniaLink Platform (buttons drawn from ``kind``)."""
        self.ensure_one()
        if not self.telegram_user_id:
            return False
        return self.env['telegram.service'].with_company(self.company_id).donialink_post('telegram/owner', {
            'company_id': self.company_id.id,
            'box_id': self.id,
            'telegram_user_id': self.telegram_user_id,
            'kind': kind,
            'text': text,
            'data': data or {},
        })

    def _card_text(self):
        self.ensure_one()
        currency = self.currency_id
        if self.balance < 0:
            text = _('Your cash box: %(balance)s · The business owes you %(owed)s',
                     balance=currency.format(self.balance), owed=currency.format(-self.balance))
        else:
            text = _('Your cash box: %s', currency.format(self.balance))
        if self.uncollected_session_count:
            text += ' · ' + _('%(count)s closed session(s) not collected (%(amount)s)',
                              count=self.uncollected_session_count, amount=currency.format(self.uncollected_amount))
        return text

    def action_generate_link(self):
        """A new one-time code registered on the platform; it answers the deep link the owner opens
        (t.me/<bot>?start=<code>)."""
        for box in self:
            code = ''.join(secrets.choice(LINK_ALPHABET) for _i in range(10))
            try:
                answer = self.env['telegram.service'].with_company(box.company_id).donialink_post(
                    'telegram/owner-link',
                    {'company_id': box.company_id.id, 'box_id': box.id, 'code': code, 'owner': box.name})
            except UserError as e:
                answer = {}
                box.message_post(body=_('The DoniaLink Platform did not register the code (%s): the link will '
                                        'work once it does.', e.args[0] if e.args else e))
            box.write({'link_code': code, 'link_url': answer.get('url') or False})
            box.message_post(body=_('New Telegram link code created.'))
        return True

    def _telegram_link(self, telegram_user_id, name=None):
        self.ensure_one()
        self.write({'telegram_user_id': str(telegram_user_id), 'telegram_name': name or False, 'link_code': False})
        self.message_post(body=_('Linked to Telegram user %s.', name or telegram_user_id))

    def action_unlink_telegram(self):
        self.write({'telegram_user_id': False, 'telegram_name': False, 'link_code': False, 'link_url': False})
        for box in self:
            box.message_post(body=_('Telegram unlinked.'))
        return True

    def action_send_statement(self):
        """Statement of the period since the last one (or the last 7 days), sent now."""
        for box in self:
            today = fields.Date.context_today(box)
            last = box.statement_ids[:1]
            date_from = last.date_to + timedelta(days=1) if last else today - timedelta(days=7)
            box._create_statement(min(date_from, today), today)._send()
        return True

    def _open(self, model, domain, name):
        return {'type': 'ir.actions.act_window', 'name': name, 'res_model': model,
                'views': [(False, 'list'), (False, 'form')], 'domain': domain,
                'context': {'default_box_id': self.id}}

    def action_view_moves(self):
        self.ensure_one()
        return self._open('ecc.owner.move', [('box_id', '=', self.id)], _('Movements of %s', self.name))

    def action_view_uncollected(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('Sessions not collected'), 'res_model': 'pos.session',
                'views': [(False, 'list'), (False, 'form')],
                'domain': [('id', 'in', self._uncollected_sessions().ids)]}

    def action_view_receipts(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('expense_cash_control_telegram.action_ecc_receipt')
        action['domain'] = [('owner_box_id', '=', self.id)]
        return action

    def action_view_differences(self):
        self.ensure_one()
        return self._open('ecc.owner.difference', [('box_id', '=', self.id)], _('Differences of %s', self.name))

    def action_view_statements(self):
        self.ensure_one()
        return self._open('ecc.owner.statement', [('box_id', '=', self.id)], _('Statements of %s', self.name))


class OwnerMove(models.Model):
    _name = 'ecc.owner.move'
    _description = 'Owner Cash Movement'
    _order = 'date desc, id desc'

    box_id = fields.Many2one('ecc.owner.box', string='Cash Box', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='box_id.company_id', store=True, index=True)
    currency_id = fields.Many2one(related='box_id.currency_id')
    date = fields.Datetime(required=True, default=fields.Datetime.now, index=True)
    kind = fields.Selection([
        ('collect', 'Collected'),
        ('expense', 'Expense'),
        ('drawing', 'Took for Me'),
        ('deposit', 'Deposit'),
        ('adjust', 'Adjustment'),
    ], string='Type', required=True, index=True)
    name = fields.Char('Description', required=True)
    amount = fields.Monetary('Amount', required=True, help='Effect on the balance: + in, − out.')
    state = fields.Selection([('posted', 'Posted'), ('cancelled', 'Cancelled')], default='posted',
                             required=True, index=True)
    source = fields.Selection([('telegram', 'Telegram'), ('pos', 'POS'), ('odoo', 'Odoo')], default='odoo')
    deposit_target = fields.Selection([('bank', 'Bank'), ('till', 'Till')])
    session_id = fields.Many2one('pos.session', string='POS Session', index='btree_not_null', ondelete='set null')
    cash_move_id = fields.Many2one('pos.cash.move', string='POS Cash-Out', index='btree_not_null',
                                   ondelete='cascade')
    statement_line_id = fields.Many2one('account.bank.statement.line', ondelete='set null')
    expense_id = fields.Many2one('expense.express', string='Expense', index='btree_not_null', ondelete='cascade')
    payment_id = fields.Many2one('account.payment', string='Payment', index='btree_not_null', ondelete='cascade')
    receipt_id = fields.Many2one('ecc.receipt', string='Receipt', ondelete='set null')
    difference_id = fields.Many2one('ecc.owner.difference', ondelete='cascade')
    account_move_id = fields.Many2one('account.move', string='Journal Entry', ondelete='set null')

    def action_open_entry(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'account.move', 'res_id': self.account_move_id.id,
                'views': [(False, 'form')]}

    def _kind_label(self):
        return dict(self._fields['kind']._description_selection(self.env))[self.kind]

    def _bot_line(self, running=None):
        self.ensure_one()
        local = fields.Datetime.context_timestamp(self, self.date)
        line = '%s · %s · %s' % (local.strftime('%d/%m %H:%M'), self._kind_label(),
                                 self.currency_id.format(self.amount))
        if running is not None:
            line += ' → %s' % self.currency_id.format(running)
        return line


class OwnerDifference(models.Model):
    """Something the accountant explains: a partial collection ("Other amount"), a count of the owner's cash
    that does not match, or a disputed statement."""
    _name = 'ecc.owner.difference'
    _description = 'Owner Cash Difference'
    _inherit = ['mail.thread']
    _order = 'id desc'

    box_id = fields.Many2one('ecc.owner.box', string='Cash Box', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='box_id.company_id', store=True, index=True)
    currency_id = fields.Many2one(related='box_id.currency_id')
    date = fields.Datetime(default=fields.Datetime.now, required=True)
    kind = fields.Selection([
        ('collection', 'Partial Collection'),
        ('count', 'Cash Count'),
        ('statement', 'Disputed Statement'),
    ], string='Type', required=True)
    amount = fields.Monetary('Difference', help='Partial collection: cash left in the session.\n'
                                                'Cash count: counted − expected (negative = missing).')
    counted = fields.Monetary('Counted')
    expected = fields.Monetary('Expected')
    session_id = fields.Many2one('pos.session', string='POS Session', ondelete='set null', index='btree_not_null')
    statement_id = fields.Many2one('ecc.owner.statement', string='Statement', ondelete='set null')
    note = fields.Text('Note')
    resolution = fields.Selection([
        ('left_in_till', 'Left in Till'),
        ('loss', 'Loss / Gain'),
        ('error', 'Counting Error'),
        ('explained', 'Explained'),
    ], tracking=True)
    category_id = fields.Many2one('expense.category', string='Category',
                                  domain="[('company_id', 'in', [False, company_id])]",
                                  help='Account of the loss (or gain).')
    state = fields.Selection([('pending', 'To Explain'), ('done', 'Explained'), ('cancelled', 'Cancelled')],
                             default='pending', required=True, tracking=True, index=True)
    move_ids = fields.One2many('ecc.owner.move', 'difference_id')

    @api.depends('box_id', 'kind', 'date')
    def _compute_display_name(self):
        labels = dict(self._fields['kind']._description_selection(self.env))
        for difference in self:
            difference.display_name = '%s · %s' % (difference.box_id.name, labels.get(difference.kind, ''))

    def action_resolve(self):
        for difference in self.filtered(lambda d: d.state == 'pending'):
            if not difference.resolution:
                raise UserError(_('Choose how the difference is explained.'))
            if difference.resolution == 'loss':
                difference._post_loss()
            difference.state = 'done'
        return True

    def _post_loss(self):
        self.ensure_one()
        category = self.category_id
        if not category or not category.account_id:
            raise UserError(_('Choose a category with an account for the loss.'))
        box = self.box_id
        amount = abs(self.amount)
        if float_is_zero(amount, precision_rounding=box.currency_id.rounding):
            raise UserError(_('There is no amount to record.'))
        if self.kind == 'collection':
            # the cash left in the session is lost: out of the POS cash journal, on the category account
            label = _('Loss on collection of %s', self.session_id.name)
            st_line = self.env['account.bank.statement.line'].sudo().create({
                'journal_id': self.session_id.cash_journal_id.id, 'amount': -amount, 'payment_ref': label,
                'date': fields.Date.context_today(self), 'counterpart_account_id': category.account_id.id,
            })
            self.message_post(body=_('Loss recorded: %s', st_line.move_id._get_html_link()))
            return
        # owner's cash: missing (amount < 0) -> loss; extra (amount > 0) -> gain
        label = _('Cash difference – %s', box.name)
        if self.amount < 0:
            entry = box._post_entry(label, category.account_id, box._cash_account(), amount)
        else:
            entry = box._post_entry(label, box._cash_account(), category.account_id, amount)
        box._add_move('adjust', self.amount, label, difference_id=self.id, account_move_id=entry.id)

    def action_reset(self):
        for difference in self.filtered(lambda d: d.state == 'done'):
            if difference.move_ids.filtered(lambda m: m.state == 'posted'):
                raise UserError(_('This difference already changed the balance; it cannot be reopened.'))
            difference.state = 'pending'
        return True


class OwnerStatement(models.Model):
    _name = 'ecc.owner.statement'
    _description = 'Owner Cash Statement'
    _inherit = ['mail.thread']
    _order = 'date_to desc, id desc'

    box_id = fields.Many2one('ecc.owner.box', string='Cash Box', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='box_id.company_id', store=True)
    currency_id = fields.Many2one(related='box_id.currency_id')
    date_from = fields.Date('From', required=True)
    date_to = fields.Date('To', required=True)
    opening = fields.Monetary('Opening Balance')
    collected = fields.Monetary('Collected')
    spent = fields.Monetary('Spent')
    took = fields.Monetary('Took for Me')
    deposited = fields.Monetary('Deposited')
    adjusted = fields.Monetary('Adjustments')
    closing = fields.Monetary('Closing Balance')
    state = fields.Selection([
        ('draft', 'Not Sent'), ('sent', 'Waiting for Owner'), ('confirmed', 'Confirmed'), ('disputed', 'Disputed'),
    ], default='draft', required=True, tracking=True)
    answer_note = fields.Text('Owner Note')
    answered_at = fields.Datetime('Answered On', readonly=True)

    @api.depends('date_from', 'date_to', 'box_id')
    def _compute_display_name(self):
        for statement in self:
            statement.display_name = '%s: %s → %s' % (statement.box_id.name, statement.date_from, statement.date_to)

    def _text(self):
        self.ensure_one()
        fmt = self.currency_id.format
        lines = [
            _('Statement %(start)s → %(end)s', start=self.date_from.strftime('%d/%m'),
              end=self.date_to.strftime('%d/%m')),
            _('Opening balance: %s', fmt(self.opening)),
            _('Collected: +%s', fmt(self.collected)),
            _('Spent: −%s', fmt(self.spent)),
            _('Took for me: −%s', fmt(self.took)),
            _('Deposited: −%s', fmt(self.deposited)),
        ]
        if self.adjusted:
            lines.append(_('Adjustments: %s', fmt(self.adjusted)))
        lines.append(_('Closing balance: %s', fmt(self.closing)))
        if self.closing < 0:
            lines.append(_('The business owes you %s', fmt(-self.closing)))
        return '\n'.join(lines)

    def _send(self):
        for statement in self:
            answer = statement.box_id._platform_send('statement', statement._text(),
                                                     {'statement_id': statement.id}) or {}
            if answer.get('delivered'):
                statement.state = 'sent'
            else:
                statement.message_post(body=_('The DoniaLink bot could not deliver the statement: %s',
                                              answer.get('message') or _('owner not reachable')))

    def action_send(self):
        self._send()
        return True

    def _answer(self, correct, note=None):
        self.ensure_one()
        if self.state not in ('sent', 'draft'):
            return self
        self.write({'state': 'confirmed' if correct else 'disputed', 'answer_note': note or False,
                    'answered_at': fields.Datetime.now()})
        if not correct:
            self.env['ecc.owner.difference'].sudo().create({
                'box_id': self.box_id.id, 'kind': 'statement', 'statement_id': self.id,
                'expected': self.closing, 'note': note or _('The owner says the statement is not correct.'),
            })
        return self
