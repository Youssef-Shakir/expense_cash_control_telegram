# -*- coding: utf-8 -*-
import base64
import json
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import HttpCase, tagged

from odoo.addons.expense_cash_control.tests.common import ExpenseCashCommon

from .owner_calls import CallError, owner_call

PHOTO = base64.b64encode(b'\x89PNG\r\n\x1a\n-ecc-card-expense').decode()


class CardSetup:

    @classmethod
    def _card_setup(cls, env, prefix):
        Account = env['account.account']
        cls.drawings = Account.create({'name': '%s Drawings' % prefix, 'code': '%s310' % prefix,
                                       'account_type': 'equity'})
        cls.till = env['account.journal'].create({'name': '%s Till' % prefix, 'code': '%sT' % prefix, 'type': 'cash'})
        cls.bank = env['account.journal'].create({'name': '%s Card Bank' % prefix, 'code': '%sB' % prefix,
                                                  'type': 'bank'})
        cls.cash_method = env['pos.payment.method'].create({'name': '%s Cash' % prefix, 'journal_id': cls.till.id})
        cls.card_method = env['pos.payment.method'].create({'name': '%s Card' % prefix, 'journal_id': cls.bank.id})
        cls.config = env['pos.config'].create({
            'name': '%s POS' % prefix, 'payment_method_ids': [(6, 0, (cls.cash_method | cls.card_method).ids)]})
        cls.product = env['product.product'].create({'name': '%s Coffee' % prefix, 'available_in_pos': True,
                                                     'list_price': 10.0, 'taxes_id': [(6, 0, [])]})
        cls.partner = env['res.partner'].create({'name': '%s Customer' % prefix})
        cls.ali = env['ecc.owner.box'].create({'name': 'Ali', 'drawings_account_id': cls.drawings.id,
                                               'till_journal_id': cls.till.id})
        cls.omar = env['ecc.owner.box'].create({'name': 'Omar', 'drawings_account_id': cls.drawings.id})
        cls.stranger = env['ecc.owner.box'].create({'name': 'Stranger', 'drawings_account_id': cls.drawings.id})
        cls.card = env['ecc.owner.card'].create({
            'name': 'Rafidain card', 'journal_id': cls.bank.id, 'payment_method_ids': [(6, 0, cls.card_method.ids)],
            'box_ids': [(6, 0, (cls.ali | cls.omar).ids)], 'feed_from': fields.Date.today() - timedelta(days=1),
        })

    def _fund_card(self, amount, label='Opening balance'):
        """Money already on the card's account (a manual entry in Odoo, like an opening balance)."""
        equity = self.env['account.account'].search([('account_type', '=', 'equity')], limit=1)
        line = self.env['account.bank.statement.line'].create({
            'journal_id': self.bank.id, 'amount': amount, 'payment_ref': label, 'counterpart_account_id': equity.id})
        self.card.invalidate_recordset(['balance'])
        return line

    def _session_with_card_sales(self, card_amount, counted_diff=0.0):
        session = self.env['pos.session'].create({'config_id': self.config.id, 'user_id': self.env.uid})
        session.set_opening_control(0, '')
        order = self.env['pos.order'].create({
            'session_id': session.id, 'partner_id': self.partner.id,
            'lines': [(0, 0, {'product_id': self.product.id, 'qty': 1, 'price_unit': card_amount,
                              'price_subtotal': card_amount, 'price_subtotal_incl': card_amount})],
            'amount_total': card_amount, 'amount_tax': 0.0, 'amount_paid': 0.0, 'amount_return': 0.0,
        })
        self.env['pos.make.payment'].with_context(active_id=order.id, active_ids=order.ids).create({
            'payment_method_id': self.card_method.id, 'amount': card_amount}).check()
        session.post_closing_cash_details(0.0)
        session.close_session_from_ui([(self.card_method.id, counted_diff)] if counted_diff else None)
        self.assertEqual(session.state, 'closed')
        return session


@tagged('post_install', '-at_install')
class TestOwnerCard(CardSetup, ExpenseCashCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._card_setup(cls.env, 'ECCK')
        cls.category.owner_expense = True

    def _bank_balance(self):
        return sum(self.env['account.move.line'].search([
            ('account_id', '=', self.bank.default_account_id.id), ('parent_state', '=', 'posted')]).mapped('balance'))

    def test_card_sales_added_at_closing(self):
        session = self._session_with_card_sales(250.0, counted_diff=-10.0)
        sales = self.card.move_ids.filtered(lambda m: m.kind == 'sales')
        self.assertEqual(len(sales), 1)
        self.assertEqual(sales.session_id, session)
        self.assertAlmostEqual(sales.amount, 240.0, msg='what the terminal really paid (counted)')
        self.assertAlmostEqual(self.card.balance, 240.0)
        self.assertAlmostEqual(self._bank_balance(), 240.0, msg='the bank account follows the card')
        payment = self.env['account.payment'].search([('pos_session_id', '=', session.id)])
        self.assertTrue(payment.is_matched, 'the POS payment is matched with the bank line')
        # never twice: closing hook, button and cron
        self.card.action_feed_sales()
        self.env['ecc.owner.card']._cron_feed_sales()
        self.assertEqual(len(self.card.move_ids.filtered(lambda m: m.kind == 'sales')), 1)

    def test_withdraw_to_box_and_took_for_me(self):
        self._fund_card(1000.0)
        move = self.card._withdraw(self.ali, 300.0, 'box', note='ATM')
        self.assertEqual((move.kind, move.amount, move.box_id), ('withdraw', -300.0, self.ali))
        self.assertAlmostEqual(self.card.balance, 700.0)
        self.assertAlmostEqual(self.ali.balance, 300.0, msg='the cash is now in his box')
        self.assertEqual(move.owner_move_id.kind, 'from_card')
        self.assertAlmostEqual(self.ali.account_balance, 300.0)

        took = self.card._withdraw(self.omar, 100.0, 'took')
        self.assertEqual(took.kind, 'drawing')
        self.assertAlmostEqual(self.card.balance, 600.0)
        self.assertAlmostEqual(self.omar.balance, 0.0, msg='took for me never enters the box')
        drawing = took.account_move_id.line_ids.filtered(lambda l: l.account_id == self.drawings)
        self.assertAlmostEqual(drawing.debit, 100.0)
        self.assertAlmostEqual(self._bank_balance(), 600.0)

    def test_card_expense_and_reject(self):
        move = self.card._record_expense(
            self.omar, 80.0, self.category, note='Generator oil',
            photos=[{'content': base64.b64decode(PHOTO), 'mimetype': 'image/png'}])
        self.assertAlmostEqual(self.card.balance, -80.0)
        self.assertEqual((move.review_state, move.box_id), ('to_review', self.omar))
        self.assertTrue(move.attachment_ids)
        self.assertEqual(move.expense_id.journal_id, self.bank)
        self.assertAlmostEqual(self.omar.balance, 0.0, msg='paid by card, not from his cash')
        move.expense_id.amount = 70.0
        self.assertAlmostEqual(self.card.balance, -70.0)
        move.action_review_reject()
        self.assertAlmostEqual(self.card.balance, 0.0, msg='a rejected expense gives the amount back to the card')

    def test_owner_expense_as_vendor_payment(self):
        """The owner paid a vendor (cash box or card): the expense becomes a payment on the vendor account, his
        balance is the same, and it is offered on the vendor's bills. No purchase order."""
        payable = self.vendor.property_account_payable_id
        for pay_by_card in (False, True):
            if pay_by_card:
                move = self.card._record_expense(self.ali, 60.0, self.category, note='sugar')
                owner = self.card
            else:
                move = self.ali._record_expense(60.0, self.category, note='sugar', source='odoo')
                owner = self.ali
            owner.invalidate_recordset(['balance'])
            before = owner.balance
            expense = move.expense_id
            move.write({'review_as': 'vendor', 'vendor_id': self.vendor.id})
            self.assertTrue(move.action_review_confirm())
            self.assertFalse(expense.exists(), 'the expense is replaced, never booked twice')
            entry = move.vendor_entry_id
            self.assertEqual((entry.state, move.account_move_id, move.review_state), ('posted', entry, 'reviewed'))
            vendor_line = entry.line_ids.filtered(lambda l: l.account_id == payable)
            self.assertEqual((vendor_line.debit, vendor_line.partner_id), (60.0, self.vendor))
            owner.invalidate_recordset(['balance'])
            self.assertAlmostEqual(owner.balance, before, msg='the owner balance does not change')
            self.assertEqual(move.action_open_review()['res_id'], move.id)

            bill = self.env['account.move'].create({
                'move_type': 'in_invoice', 'partner_id': self.vendor.id, 'invoice_date': fields.Date.today(),
                'invoice_line_ids': [(0, 0, {'name': 'Sugar', 'quantity': 1, 'price_unit': 60.0, 'tax_ids': []})],
            })
            bill.action_post()
            line = next(c for c in bill.invoice_outstanding_credits_debits_widget['content']
                        if c['move_id'] == entry.id)
            bill.js_assign_outstanding_line(line['id'])
            self.assertIn(bill.payment_state, ('paid', 'in_payment'), 'the owner payment paid the bill')

    def test_review_as_expense_with_new_category(self):
        move = self.ali._record_expense(20.0, self.category, note='gas', source='odoo')
        other = self.category.copy({'name': 'ECC Other', 'code': 'ECC-OTH'})
        move.category_id = other
        move.action_review_confirm()
        self.assertEqual((move.review_state, move.expense_id.category_id), ('reviewed', other))
        self.assertTrue(move.photo_count >= 0)

    def test_deposit_from_box_to_card(self):
        self.card._withdraw(self.ali, 500.0, 'box')
        owner_move, card_move = self.card._deposit(self.ali, 200.0)
        self.assertEqual((owner_move.kind, owner_move.deposit_target, owner_move.card_id),
                         ('deposit', 'card', self.card))
        self.assertAlmostEqual(self.ali.balance, 300.0)
        self.assertAlmostEqual(card_move.amount, 200.0)
        self.assertAlmostEqual(self.card.balance, -300.0)

    def test_balance_check_difference(self):
        self._fund_card(1000.0)
        difference = self.card._record_count(self.ali, 990.0)
        self.assertEqual((difference.kind, difference.amount, difference.card_id), ('card_count', -10.0, self.card))
        self.assertFalse(self.card._record_count(self.ali, 1000.0))
        difference.write({'resolution': 'loss', 'category_id': self.category.id})
        difference.action_resolve()
        self.assertAlmostEqual(self.card.balance, 990.0)
        self.assertAlmostEqual(self.ali.balance, 0.0)
        line = difference.card_move_ids.account_move_id.line_ids.filtered(
            lambda l: l.account_id == self.expense_account)
        self.assertAlmostEqual(line.debit, 10.0)

    def test_balance_is_the_account_balance(self):
        self.assertEqual(self.card.account_id, self.bank.default_account_id)
        self._fund_card(500.0, 'Bank fee refund')
        self.assertAlmostEqual(self.card.balance, 500.0, msg='an entry made in Odoo changes the card balance')
        self.card._withdraw(self.ali, 120.0)
        self.assertAlmostEqual(self.card.balance, 380.0)
        self.assertAlmostEqual(self.card.balance, self._bank_balance())
        rows = self.card._api_moves()
        self.assertEqual([r['type'] for r in rows], ['withdraw', 'bank'])
        self.assertEqual(rows[1]['description'], 'Bank fee refund')
        self.assertAlmostEqual(rows[0]['balance_after'], 380.0)
        self.assertAlmostEqual(rows[1]['balance_after'], 500.0)
        with self.assertRaises(ValidationError):
            self.card.account_id = self.expense_account

    def test_only_shared_owners(self):
        with self.assertRaises(AccessError):
            self.card._withdraw(self.stranger, 10.0)
        with self.assertRaises(AccessError):
            self.card._record_expense(self.stranger, 10.0, self.category)

    def test_statement_shows_from_card(self):
        self.card._withdraw(self.ali, 50.0)
        today = fields.Date.context_today(self.ali)
        figures = self.ali._period_figures(today, today)
        self.assertAlmostEqual(figures['from_card'], 50.0)
        self.assertAlmostEqual(figures['closing'], 50.0)


@tagged('post_install', '-at_install')
class TestOwnerCardApp(CardSetup, HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls._card_setup(env, 'ECCQ')
        account = env['account.account'].create({'name': 'ECCQ Expense', 'code': 'ECCQ601', 'account_type': 'expense'})
        cls.category = env['expense.category'].create({'name': 'ECCQ Oil', 'code': 'ECCQ-OIL', 'account_id': account.id,
                                                       'owner_expense': True})
        wizard = env['ecc.owner.app.access'].with_context(ecc_owner_box_id=cls.ali.id).create({
            'mode': 'new', 'login': 'ali_card_app', 'password': 'ali-card-pass-1', 'lang': 'en_US'})
        wizard.action_confirm()
        other_bank = env['account.journal'].create({'name': 'ECCQ Other Bank', 'code': 'ECCQO', 'type': 'bank'})
        cls.other_card = env['ecc.owner.card'].create({'name': 'Not his', 'journal_id': other_bank.id,
                                                       'box_ids': [(6, 0, cls.stranger.ids)]})

    def _api(self, action, **params):
        response = self.url_open('/ecc/owner/api/%s' % action, data=json.dumps(
            {'jsonrpc': '2.0', 'method': 'call', 'params': params, 'id': 1}),
            headers={'Content-Type': 'application/json'}, timeout=60)
        body = response.json()
        self.assertNotIn('error', body, body.get('error'))
        return body['result']

    def test_card_in_app(self):
        self._session_with_card_sales(400.0)
        info = self._api('login', login='ali_card_app', password='ali-card-pass-1')
        cards = info['boxes'][0]['cards']
        self.assertEqual([c['name'] for c in cards], ['Rafidain card'])
        self.assertAlmostEqual(cards[0]['balance'], 400.0)
        box, card = self.ali.id, self.card.id

        home = self._api('card_home', box_id=box, card_id=card)
        self.assertEqual(home['moves'][0]['type'], 'sales')

        result = self._api('card_withdraw', box_id=box, card_id=card, amount=150, target='box', request_uid='w-0001-abc')
        self.assertTrue(result['ok'], result)
        self.assertAlmostEqual(result['bank_card']['balance'], 250.0)
        self.assertAlmostEqual(result['card']['balance'], 150.0)
        again = self._api('card_withdraw', box_id=box, card_id=card, amount=150, target='box', request_uid='w-0001-abc')
        self.assertTrue(again.get('replayed'), 'a retry never withdraws twice')

        result = self._api('card_expense', box_id=box, card_id=card, amount=40, category_id=self.category.id,
                           note='oil', photos=[{'content_b64': PHOTO, 'mimetype': 'image/png'}],
                           request_uid='e-0001-abc')
        self.assertTrue(result['ok'], result)
        self.assertAlmostEqual(result['bank_card']['balance'], 210.0)

        result = self._api('deposit', box_id=box, amount=100, target='card', card_id=card, request_uid='d-0001-abc')
        self.assertTrue(result['ok'], result)
        self.assertAlmostEqual(result['bank_card']['balance'], 310.0)
        self.assertAlmostEqual(result['card']['balance'], 50.0)

        result = self._api('card_count', box_id=box, card_id=card, counted=300)
        self.assertAlmostEqual(result['difference'], -10.0)

        refused = self._api('card_home', box_id=box, card_id=self.other_card.id)
        self.assertEqual(refused['code'], 'forbidden')
        refused = self._api('card_withdraw', box_id=box, card_id=self.other_card.id, amount=1)
        self.assertEqual(refused['code'], 'forbidden')

    def _pushes(self, box):
        devices = self.env['mail.push.device'].search([('partner_id', '=', box.app_user_id.partner_id.id)])
        return [json.loads(p.payload) for p in self.env['mail.push'].search([('mail_push_device_id', 'in', devices.ids)])]

    def test_notification_settings_in_app(self):
        self._api('login', login='ali_card_app', password='ali-card-pass-1')
        n = self._api('notifications', box_id=self.ali.id)['notifications']
        self.assertTrue(n['reminder_expense'])
        result = self._api('notifications_set', box_id=self.ali.id, reminder_expense=False,
                           reminder_count_weekday='0', reminder_hour=20, ignored='x')
        self.assertTrue(result['ok'])
        self.assertEqual((self.ali.reminder_expense, self.ali.reminder_count_weekday, self.ali.reminder_hour),
                         (False, '0', 20))
        refused = self._api('notifications_set', box_id=self.ali.id, reminder_hour=99)
        self.assertEqual(refused['code'], 'refused')
        self.assertEqual(self._api('notifications', box_id=self.stranger.id)['code'], 'forbidden')

    def test_push_notifications(self):
        self._api('login', login='ali_card_app', password='ali-card-pass-1')
        key = self._api('push_key')['key']
        self.assertTrue(key)
        refused = self._api('push_subscribe', endpoint='https://push.example.com/x1', vapid_key='old',
                            keys={'p256dh': 'BPub', 'auth': 'secret'})
        self.assertEqual(refused['code'], 'push_key')
        self._api('push_subscribe', endpoint='https://push.example.com/x1', vapid_key=key,
                  keys={'p256dh': 'BPub', 'auth': 'secret'}, expiration=None)
        self.assertEqual(self.ali.app_push_count, 1)
        self.env['mail.push'].search([]).unlink()

        # a co-owner uses the shared card: Ali is told, Omar (who did it) is not
        self._fund_card(300.0)
        self.card._withdraw(self.omar, 100.0, 'took')
        pushes = self._pushes(self.ali)
        self.assertEqual(len(pushes), 1)
        self.assertIn('Rafidain card', pushes[0]['title'])
        self.assertIn('Omar', pushes[0]['options']['body'])
        self.assertEqual(pushes[0]['options']['data']['url'],
                         '/dl/app#cashbox/%s/card/%s' % (self.ali.id, self.card.id))

        # card sales of a closed session, and the session to collect
        self.env['mail.push'].search([]).unlink()
        self.ali.notify_session_close = True
        self._session_with_card_sales(40.0)
        titles = [p['title'] for p in self._pushes(self.ali)]
        self.assertTrue(any('Rafidain card' in t for t in titles), titles)

        # his card expense rejected
        self.env['mail.push'].search([]).unlink()
        move = self.card._record_expense(self.ali, 25.0, self.category, note='oil')
        self.assertFalse(self._pushes(self.ali), 'no notification for what he did himself')
        move.action_review_reject()
        pushes = self._pushes(self.ali)
        self.assertEqual(pushes[-1]['title'], 'Expense rejected')
        self.assertIn('back on the card', pushes[-1]['options']['body'])

        self._api('push_unsubscribe', endpoint='https://push.example.com/x1')
        self.assertEqual(self.ali.app_push_count, 0)


@tagged('post_install', '-at_install')
class TestOwnerService(CardSetup, ExpenseCashCommon):
    """Cash box actions done for the owner by someone else (Sara, the manager)."""

    ACTOR = 'Sara (manager)'

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._card_setup(cls.env, 'ECCP')
        cls.category.owner_expense = True

    def _tool(self, name, box=None, **params):
        return owner_call(self.env, box or self.ali, name, actor=self.ACTOR, **params)

    def _app_login(self):
        if not self.ali.app_user_id:
            wizard = self.env['ecc.owner.app.access'].with_context(ecc_owner_box_id=self.ali.id).create({
                'mode': 'new', 'login': 'ali_owner_tools', 'password': 'ali-owner-pass-1', 'lang': 'en_US'})
            wizard.action_confirm()
        return self.ali.app_user_id

    def _sent(self, kind):
        """Ali's DoniaLink App inbox messages of this kind (the owner is told there, not on the platform)."""
        return self.env['donialink.app.message'].search([('kind_code', '=', 'owner_' + kind),
                                                          ('user_id', '=', self.ali.app_user_id.id or 0)])

    def _forget(self):
        self.env['donialink.app.message'].search([]).unlink()

    def test_card_actions_for_the_owner(self):
        self._fund_card(500.0)
        cards = self._tool('cards')['cards']
        self.assertEqual([c['card_id'] for c in cards], [self.card.id])
        self.assertAlmostEqual(cards[0]['balance'], 500.0)

        uid = 'a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6'
        result = self._tool('card_withdraw', card_id=self.card.id, amount=100.0, target='box', request_uid=uid)
        self.assertAlmostEqual(result['bank_card']['balance'], 400.0)
        self.assertAlmostEqual(result['card']['balance'], 100.0)
        again = self._tool('card_withdraw', card_id=self.card.id, amount=100.0, target='box', request_uid=uid)
        self.assertTrue(again['replayed'])
        self.assertAlmostEqual(self.card.balance, 400.0, msg='a retry never withdraws twice')
        move = self.card.move_ids.filtered(lambda m: m.kind == 'withdraw')
        self.assertEqual(move.source, 'app')
        self.assertIn('Sara (manager) via DoniaLink app', self.ali.message_ids[0].body)

        result = self._tool('card_expense', card_id=self.card.id, amount=30.0, category_id=self.category.id,
                            note='oil', photos=[{'content_b64': PHOTO, 'mimetype': 'image/png'}],
                            request_uid='e' * 32)
        self.assertAlmostEqual(result['bank_card']['balance'], 370.0)
        self.assertIsNone(result['receipt_id'])
        card_expense = self.card.move_ids.filtered(lambda m: m.kind == 'expense')
        self.assertIn('Owner App', card_expense.expense_id.notes)

        result = self._tool('deposit', amount=50.0, target='card', card_id=self.card.id, request_uid='d' * 32)
        self.assertAlmostEqual(result['bank_card']['balance'], 420.0)
        self.assertAlmostEqual(result['balance'], 50.0, msg='box tools keep the balance card at the top level')

        home = self._tool('card_home', card_id=self.card.id, limit=10)
        self.assertEqual([m['type'] for m in home['moves']][:3], ['deposit', 'expense', 'withdraw'])
        result = self._tool('card_count', card_id=self.card.id, counted=400.0)
        self.assertAlmostEqual(result['difference'], -20.0)

        with self.assertRaises(CallError) as error:
            self._tool('card_home', box=self.stranger, card_id=self.card.id)
        self.assertEqual(error.exception.code, 'forbidden')

        statements = self._tool('statements')
        self.assertIn('statements', statements)

    def test_notifications_in_the_app(self):
        self._app_login()
        self._fund_card(200.0)
        self.card._withdraw(self.omar, 80.0, 'took')
        sent = self._sent('card_move')
        self.assertEqual(len(sent), 1, 'Ali is told; Omar (who did it, no app login) is not')
        self.assertEqual(sent.url, '#cashbox/%s/card/%s' % (self.ali.id, self.card.id))
        self.assertEqual(sent.company_id, self.ali.company_id)
        self.assertTrue(sent.origin.startswith('owner_cash_box:card-move-'))

        self._forget()
        self._session_with_card_sales(60.0)
        self.assertTrue(self._sent('card_sales'))

        self._forget()
        move = self.card._record_expense(self.ali, 10.0, self.category)
        move.action_review_reject()
        self.assertEqual(len(self._sent('expense_rejected')), 1)

    def test_two_people_same_box(self):
        """Sara and Ali act on the same box: same data, Ali told once."""
        wizard = self.env['ecc.owner.app.access'].with_context(ecc_owner_box_id=self.ali.id).create({
            'mode': 'new', 'login': 'ali_both_apps', 'password': 'ali-both-pass-1'})
        wizard.action_confirm()
        self.env['mail.push.device'].sudo().create({
            'partner_id': self.ali.app_user_id.partner_id.id, 'endpoint': 'https://push.example.com/both',
            'keys': json.dumps({'p256dh': 'BPub', 'auth': 'secret'})})
        self._fund_card(300.0)

        # a move on the DoniaLink app shows in the Odoo app (and the platform flag does not hide the box there)
        self._tool('card_withdraw', card_id=self.card.id, amount=50.0, target='box', request_uid='p' * 32)
        app = self.env['ecc.owner.service'].with_user(self.ali.app_user_id).with_context(ecc_source='app')
        self.assertAlmostEqual(app.cards(self.ali)['cards'][0]['balance'], 250.0)
        self.assertAlmostEqual(app.statements(self.ali)['card']['balance'], 50.0)
        # the same request id seen from the Odoo app is a replay, not a second withdrawal
        again = app.card_withdraw(self.ali, self.card.id, 50.0, 'box', '', 'p' * 32)
        self.assertTrue(again['replayed'])
        self.assertAlmostEqual(self.card.balance, 250.0)

        # a co-owner's move: Ali's phone is notified once, and the message is in the app inbox
        self.env['mail.push'].search([]).unlink()
        self._forget()
        self.card._withdraw(self.omar, 20.0, 'took')
        self.assertEqual(len(self.env['mail.push'].search([])), 1, 'one phone notification, not two')
        self.assertEqual(len(self._sent('card_move')), 1)

    def test_same_request_at_the_same_moment(self):
        self._fund_card(100.0)
        uid = 'c' * 32
        self._tool('card_withdraw', card_id=self.card.id, amount=10.0, target='box', request_uid=uid)
        # the second request did not see the first one yet (its transaction was not committed)
        with patch.object(type(self.env['ecc.owner.service']), '_card_replay', return_value=None), \
                self.assertRaises(CallError) as error:
            self._tool('card_withdraw', card_id=self.card.id, amount=10.0, target='box', request_uid=uid)
        self.assertEqual((error.exception.code, error.exception.status), ('duplicate', 409))
        self.assertAlmostEqual(self.card.balance, 90.0)

    def test_reminders(self):
        import pytz
        from datetime import datetime, time
        tz = pytz.timezone('Asia/Baghdad')
        self.ali.company_id.partner_id.tz = 'Asia/Baghdad'
        self._app_login().tz = 'Asia/Baghdad'
        self.ali.write({'reminder_hour': 21,
                        'reminder_count_weekday': str(self.ali._owner_now().weekday())})
        today = self.ali._owner_now().date()
        at = lambda hour: tz.localize(datetime.combine(today, time(hour, 30)))   # noqa: E731

        self.ali._run_reminders(at(20))
        self.assertFalse(self._sent('reminder_expense') or self._sent('reminder_count'), 'nothing before the hour')
        self.assertFalse(self.ali._expense_reminder_due(at(20)))

        self.ali._run_reminders(at(21))
        expense, count = self._sent('reminder_expense'), self._sent('reminder_count')
        self.assertEqual((len(expense), len(count)), (1, 1))
        self.assertIn("haven't recorded any cash expense today", expense.preview)
        self.assertEqual(expense.url, '#cashbox/%s/expense' % self.ali.id)
        self.assertEqual(expense.origin, 'owner_cash_box:reminder-%s-%s' % (self.ali.id, today))
        self.assertEqual(count.url, '#cashbox/%s/count' % self.ali.id)
        self.assertTrue(count.origin.startswith('owner_cash_box:count-%s-' % self.ali.id))

        self._forget()
        self.ali._run_reminders(at(22))
        self.assertFalse(self._sent('reminder_expense') or self._sent('reminder_count'), 'each reminder once a day')

        # something recorded today: no expense reminder (the count day still asks to count)
        self.ali.write({'reminder_expense_on': False, 'reminder_count_on': False})
        noon = tz.localize(datetime.combine(today, time(12))).astimezone(pytz.utc).replace(tzinfo=None)
        self.env['ecc.owner.move'].create({'box_id': self.ali.id, 'kind': 'drawing', 'name': 'took',
                                           'amount': -5.0, 'date': noon})
        self.assertTrue(self.ali._api_card()['recorded_today'])
        self.assertFalse(self.ali._expense_reminder_due(at(21)))
        self.ali._run_reminders(at(21))
        self.assertFalse(self._sent('reminder_expense'))
        self.assertEqual(len(self._sent('reminder_count')), 1)

    def test_notification_settings(self):
        n = self._tool('notifications')['notifications']
        self.assertEqual(n, {'session_closed': True, 'reminder_expense': True, 'reminder_count_weekday': '4',
                             'reminder_hour': 21})
        result = self._tool('notifications_set', reminder_expense=False, reminder_count_weekday=None,
                            reminder_hour=8)
        self.assertEqual(result['notifications'], {'session_closed': True, 'reminder_expense': False,
                                                   'reminder_count_weekday': None, 'reminder_hour': 8})
        self.assertFalse(self.ali.reminder_count_weekday)
        self.assertIn('notification settings changed', self.ali.message_ids[0].body)
        # only what is given changes
        self._tool('notifications_set', session_closed=False)
        self.assertEqual((self.ali.notify_session_close, self.ali.reminder_hour), (False, 8))
        with self.assertRaises(CallError) as error:
            self._tool('notifications_set', reminder_hour=30)
        self.assertEqual(error.exception.code, 'refused')
        with self.assertRaises(CallError):
            self._tool('notifications_set', reminder_count_weekday='9')
