# -*- coding: utf-8 -*-
import base64
import json
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import HttpCase, tagged

from odoo.addons.expense_cash_control.tests.common import ExpenseCashCommon

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

    def setUp(self):
        super().setUp()
        patcher = patch.object(type(self.env['telegram.service']), 'donialink_post',
                               return_value={'ok': True, 'delivered': True})
        patcher.start()
        self.addCleanup(patcher.stop)

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
        move, receipt = self.card._record_expense(
            self.omar, 80.0, self.category, note='Generator oil',
            photos=[{'content': base64.b64decode(PHOTO), 'mimetype': 'image/png'}])
        self.assertAlmostEqual(self.card.balance, -80.0)
        self.assertEqual(receipt.card_id, self.card)
        self.assertEqual(receipt.owner_box_id, self.omar)
        self.assertEqual(move.expense_id.journal_id, self.bank)
        self.assertAlmostEqual(self.omar.balance, 0.0, msg='paid by card, not from his cash')
        move.expense_id.amount = 70.0
        self.assertAlmostEqual(self.card.balance, -70.0)
        receipt.action_reject()
        self.assertAlmostEqual(self.card.balance, 0.0, msg='a rejected expense gives the amount back to the card')

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
            'mode': 'new', 'login': 'ali_card_app', 'password': 'ali-card-pass-1'})
        wizard.action_confirm()
        other_bank = env['account.journal'].create({'name': 'ECCQ Other Bank', 'code': 'ECCQO', 'type': 'bank'})
        cls.other_card = env['ecc.owner.card'].create({'name': 'Not his', 'journal_id': other_bank.id,
                                                       'box_ids': [(6, 0, cls.stranger.ids)]})

    def setUp(self):
        super().setUp()
        patcher = patch.object(type(self.env['telegram.service']), 'donialink_post',
                               return_value={'ok': True, 'delivered': True})
        patcher.start()
        self.addCleanup(patcher.stop)

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
                         '/ecc/owner/app?box=%s&card=%s#bankcard' % (self.ali.id, self.card.id))

        # card sales of a closed session, and the session to collect
        self.env['mail.push'].search([]).unlink()
        self.ali.notify_session_close = True
        self._session_with_card_sales(40.0)
        titles = [p['title'] for p in self._pushes(self.ali)]
        self.assertTrue(any('Rafidain card' in t for t in titles), titles)

        # his card expense rejected
        self.env['mail.push'].search([]).unlink()
        _move, receipt = self.card._record_expense(self.ali, 25.0, self.category, note='oil')
        self.assertFalse(self._pushes(self.ali), 'no notification for what he did himself')
        receipt.action_reject()
        pushes = self._pushes(self.ali)
        self.assertEqual(pushes[-1]['title'], 'Expense rejected')
        self.assertIn('back on the card', pushes[-1]['options']['body'])

        self._api('push_unsubscribe', endpoint='https://push.example.com/x1')
        self.assertEqual(self.ali.app_push_count, 0)


@tagged('post_install', '-at_install')
class TestOwnerPlatformTools(CardSetup, ExpenseCashCommon):
    """Connector tools used by the DoniaLink app: platform user instead of a Telegram link."""

    APP_USER = {'id': 'dl:42', 'name': 'Sara (manager)'}

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._card_setup(cls.env, 'ECCP')
        cls.category.owner_expense = True
        cls.tools = cls.env['donialink.agent.tools']

    def setUp(self):
        super().setUp()
        patcher = patch.object(type(self.env['telegram.service']), 'donialink_post',
                               return_value={'ok': True, 'delivered': True})
        self.platform = patcher.start()
        self.addCleanup(patcher.stop)

    def _tool(self, name, **params):
        params.setdefault('box_id', self.ali.id)
        params.setdefault('app_user', self.APP_USER)
        return self.tools._run_tool(name, params)[1]

    def _sent(self, kind):
        return [c.args[1] for c in self.platform.call_args_list
                if c.args and c.args[0] == 'telegram/owner' and c.args[1]['kind'] == kind]

    def test_boxes_and_platform_link(self):
        boxes = self.tools._run_tool('owner_boxes', {})[1]['boxes']
        ids = [b['box_id'] for b in boxes]
        self.assertIn(self.ali.id, ids)
        self.assertIn(self.stranger.id, ids)
        self.assertFalse(next(b for b in boxes if b['box_id'] == self.ali.id)['on_platform'])
        result = self.tools._run_tool('owner_platform_link', {'box_id': self.ali.id, 'enabled': True})[1]
        self.assertEqual(result, {'box_id': self.ali.id, 'on_platform': True})
        self.assertTrue(self.ali.platform_enabled)

    def test_identity_required(self):
        from odoo.addons.donialink_agent.models.agent_registry import ToolError
        with self.assertRaises(ToolError) as error:
            self.tools._run_tool('owner_card', {'box_id': self.ali.id})
        self.assertEqual(error.exception.code, 'invalid_params')
        with self.assertRaises(ToolError) as error:
            self.tools._run_tool('owner_card', {'box_id': self.ali.id, 'telegram_user_id': '999'})
        self.assertEqual(error.exception.code, 'not_linked')

    def test_card_tools_with_app_user(self):
        from odoo.addons.donialink_agent.models.agent_registry import ToolError
        self._fund_card(500.0)
        cards = self._tool('owner_cards')['cards']
        self.assertEqual([c['card_id'] for c in cards], [self.card.id])
        self.assertAlmostEqual(cards[0]['balance'], 500.0)

        uid = 'a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6'
        result = self._tool('owner_card_withdraw', card_id=self.card.id, amount=100.0, target='box', request_uid=uid)
        self.assertAlmostEqual(result['bank_card']['balance'], 400.0)
        self.assertAlmostEqual(result['card']['balance'], 100.0)
        again = self._tool('owner_card_withdraw', card_id=self.card.id, amount=100.0, target='box', request_uid=uid)
        self.assertTrue(again['replayed'])
        self.assertAlmostEqual(self.card.balance, 400.0, msg='a retry never withdraws twice')
        move = self.card.move_ids.filtered(lambda m: m.kind == 'withdraw')
        self.assertEqual(move.source, 'platform')
        self.assertIn('Sara (manager) via DoniaLink app', self.ali.message_ids[0].body)

        result = self._tool('owner_card_expense', card_id=self.card.id, amount=30.0, category_id=self.category.id,
                            note='oil', photos=[{'content_b64': PHOTO, 'mimetype': 'image/png'}],
                            request_uid='e' * 32)
        self.assertAlmostEqual(result['bank_card']['balance'], 370.0)
        receipt = self.env['ecc.receipt'].browse(result['receipt_id'])
        self.assertIn('DoniaLink App', receipt.expense_id.notes)

        result = self._tool('owner_deposit', amount=50.0, target='card', card_id=self.card.id, request_uid='d' * 32)
        self.assertAlmostEqual(result['bank_card']['balance'], 420.0)
        self.assertAlmostEqual(result['balance'], 50.0, msg='box tools keep the balance card at the top level')

        home = self._tool('owner_card_home', card_id=self.card.id, limit=10)
        self.assertEqual([m['type'] for m in home['moves']][:3], ['deposit', 'expense', 'withdraw'])
        result = self._tool('owner_card_count', card_id=self.card.id, counted=400.0)
        self.assertAlmostEqual(result['difference'], -20.0)

        with self.assertRaises(ToolError) as error:
            self._tool('owner_card_home', box_id=self.stranger.id, card_id=self.card.id)
        self.assertEqual(error.exception.code, 'forbidden')

        statements = self._tool('owner_statements')
        self.assertIn('statements', statements)

    def test_notifications_without_telegram(self):
        self.ali.platform_enabled = True
        self._fund_card(200.0)
        self.card._withdraw(self.omar, 80.0, 'took')
        sent = self._sent('card_move')
        self.assertEqual(len(sent), 1, 'Ali is told; Omar (no Telegram, not on the platform) is not')
        payload = sent[0]
        self.assertEqual(payload['box_id'], self.ali.id)
        self.assertIsNone(payload['telegram_user_id'])
        self.assertEqual(payload['company_id'], self.ali.company_id.id)
        data = payload['data']
        self.assertEqual((data['route'], data['card_id']), ('bankcard', self.card.id))
        self.assertTrue(data['title'] and data['body'] and data['tag'])
        self.assertAlmostEqual(data['amount'], -80.0)

        self.platform.reset_mock()
        self._session_with_card_sales(60.0)
        self.assertTrue(self._sent('card_sales'))

        self.platform.reset_mock()
        _move, receipt = self.card._record_expense(self.ali, 10.0, self.category)
        receipt.action_reject()
        rejected = self._sent('expense_rejected')
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0]['data']['receipt_id'], receipt.id)

    def test_odoo_app_and_platform_side_by_side(self):
        """One box in the Odoo app, on the DoniaLink app and on Telegram at once: same data, every channel told."""
        wizard = self.env['ecc.owner.app.access'].with_context(ecc_owner_box_id=self.ali.id).create({
            'mode': 'new', 'login': 'ali_both_apps', 'password': 'ali-both-pass-1'})
        wizard.action_confirm()
        self.env['mail.push.device'].sudo().create({
            'partner_id': self.ali.app_user_id.partner_id.id, 'endpoint': 'https://push.example.com/both',
            'keys': json.dumps({'p256dh': 'BPub', 'auth': 'secret'})})
        self.ali.write({'platform_enabled': True, 'telegram_user_id': '777'})
        self._fund_card(300.0)

        # a move on the DoniaLink app shows in the Odoo app (and the platform flag does not hide the box there)
        self._tool('owner_card_withdraw', card_id=self.card.id, amount=50.0, target='box', request_uid='p' * 32)
        app = self.env['ecc.owner.service'].with_user(self.ali.app_user_id).with_context(ecc_source='app')
        self.assertAlmostEqual(app.cards(self.ali)['cards'][0]['balance'], 250.0)
        self.assertAlmostEqual(app.statements(self.ali)['card']['balance'], 50.0)
        # the same request id seen from the Odoo app is a replay, not a second withdrawal
        again = app.card_withdraw(self.ali, self.card.id, 50.0, 'box', '', 'p' * 32)
        self.assertTrue(again['replayed'])
        self.assertAlmostEqual(self.card.balance, 250.0)

        # a co-owner's move: Ali gets the Odoo push AND the platform message (its app and Telegram)
        self.env['mail.push'].search([]).unlink()
        self.platform.reset_mock()
        self.card._withdraw(self.omar, 20.0, 'took')
        self.assertEqual(len(self.env['mail.push'].search([])), 1)
        sent = self._sent('card_move')
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]['telegram_user_id'], '777')

    def test_same_request_at_the_same_moment(self):
        from odoo.addons.donialink_agent.models.agent_registry import ToolError
        self._fund_card(100.0)
        uid = 'c' * 32
        self._tool('owner_card_withdraw', card_id=self.card.id, amount=10.0, target='box', request_uid=uid)
        # the second request did not see the first one yet (its transaction was not committed)
        with patch.object(type(self.env['ecc.owner.service']), '_card_replay', return_value=None), \
                self.assertRaises(ToolError) as error:
            self._tool('owner_card_withdraw', card_id=self.card.id, amount=10.0, target='box', request_uid=uid)
        self.assertEqual((error.exception.code, error.exception.status), ('duplicate', 409))
        self.assertAlmostEqual(self.card.balance, 90.0)

    def test_reminders(self):
        import pytz
        from datetime import datetime, time
        tz = pytz.timezone('Asia/Baghdad')
        self.ali.company_id.partner_id.tz = 'Asia/Baghdad'
        self.ali.write({'platform_enabled': True, 'reminder_hour': 21,
                        'reminder_count_weekday': str(self.ali._owner_now().weekday())})
        today = self.ali._owner_now().date()
        at = lambda hour: tz.localize(datetime.combine(today, time(hour, 30)))   # noqa: E731

        self.ali._run_reminders(at(20))
        self.assertFalse(self.platform.called, 'nothing before the reminder hour')
        self.assertFalse(self.ali._expense_reminder_due(at(20)))

        self.ali._run_reminders(at(21))
        expense, count = self._sent('reminder_expense'), self._sent('reminder_count')
        self.assertEqual((len(expense), len(count)), (1, 1))
        self.assertIsNone(expense[0]['telegram_user_id'])
        self.assertIn("haven't recorded any cash expense today", expense[0]['text'])
        data = expense[0]['data']
        self.assertEqual((data['route'], data['tag']), ('expense', 'reminder-%s-%s' % (self.ali.id, today)))
        self.assertEqual(count[0]['data']['route'], 'count')
        self.assertTrue(count[0]['data']['tag'].startswith('count-%s-' % self.ali.id))

        self.platform.reset_mock()
        self.ali._run_reminders(at(22))
        self.assertFalse(self.platform.called, 'each reminder once a day')

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
        from odoo.addons.donialink_agent.models.agent_registry import ToolError
        n = self._tool('owner_notifications')['notifications']
        self.assertEqual(n, {'session_closed': True, 'reminder_expense': True, 'reminder_count_weekday': '4',
                             'reminder_hour': 21})
        result = self._tool('owner_notifications_set', reminder_expense=False, reminder_count_weekday=None,
                            reminder_hour=8)
        self.assertEqual(result['notifications'], {'session_closed': True, 'reminder_expense': False,
                                                   'reminder_count_weekday': None, 'reminder_hour': 8})
        self.assertFalse(self.ali.reminder_count_weekday)
        self.assertIn('notification settings changed', self.ali.message_ids[0].body)
        # only what is given changes
        self._tool('owner_notifications_set', session_closed=False)
        self.assertEqual((self.ali.notify_session_close, self.ali.reminder_hour), (False, 8))
        with self.assertRaises(ToolError) as error:
            self._tool('owner_notifications_set', reminder_hour=30)
        self.assertEqual(error.exception.code, 'invalid_params')
        with self.assertRaises(ToolError):
            self._tool('owner_notifications_set', reminder_count_weekday='9')
