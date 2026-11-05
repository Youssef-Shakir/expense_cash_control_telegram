# -*- coding: utf-8 -*-
import base64
import json
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.tests import HttpCase, tagged

PHOTO = base64.b64encode(b'\x89PNG\r\n\x1a\n-ecc-owner-app-photo').decode()


@tagged('post_install', '-at_install')
class TestOwnerApp(HttpCase):
    """The owner app API, called the way the phone calls it (JSON-RPC with the session cookie)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        Account = env['account.account']
        cls.expense_account = Account.create({'name': 'ECC App Expense', 'code': 'ECCA601', 'account_type': 'expense'})
        cls.drawings = Account.create({'name': 'ECC App Drawings', 'code': 'ECCA310', 'account_type': 'equity'})
        cls.transfer = Account.create({'name': 'ECC App Transfer', 'code': 'ECCA199',
                                       'account_type': 'asset_current', 'reconcile': True})
        env.company.transfer_account_id = cls.transfer
        cls.category = env['expense.category'].create({
            'name': 'ECC App Generator', 'code': 'ECCA-GEN', 'account_id': cls.expense_account.id,
            'owner_expense': True,
        })
        cls.cash_journal = env['account.journal'].create({'name': 'ECC App Till', 'code': 'ECCAT', 'type': 'cash'})
        cls.cash_method = env['pos.payment.method'].create({'name': 'ECC App Cash',
                                                            'journal_id': cls.cash_journal.id})
        cls.config = env['pos.config'].create({'name': 'ECC App POS',
                                               'payment_method_ids': [(6, 0, cls.cash_method.ids)]})
        cls.box = env['ecc.owner.box'].create({
            'name': 'Ali App', 'drawings_account_id': cls.drawings.id, 'till_journal_id': cls.cash_journal.id,
            'collect_from': fields.Date.today() - timedelta(days=1), 'pos_config_ids': [(6, 0, cls.config.ids)],
        })
        cls.other_box = env['ecc.owner.box'].create({'name': 'Omar App', 'drawings_account_id': cls.drawings.id})
        wizard = env['ecc.owner.app.access'].with_context(ecc_owner_box_id=cls.box.id).create({
            'mode': 'new', 'login': 'ali_owner_app', 'password': 'ali-owner-pass-1'})
        wizard.action_confirm()
        cls.owner_user = cls.box.app_user_id

    def setUp(self):
        super().setUp()
        patcher = patch.object(type(self.env['telegram.service']), 'donialink_post',
                               return_value={'ok': True, 'delivered': True})
        self.platform = patcher.start()
        self.addCleanup(patcher.stop)

    def _api(self, action, **params):
        response = self.url_open('/ecc/owner/api/%s' % action, data=json.dumps(
            {'jsonrpc': '2.0', 'method': 'call', 'params': params, 'id': 1}),
            headers={'Content-Type': 'application/json'})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertNotIn('error', body, body.get('error'))
        return body['result']

    def _login(self):
        info = self._api('login', login='ali_owner_app', password='ali-owner-pass-1')
        self.assertTrue(info['ok'])
        return info

    def _closed_session(self, cash):
        session = self.env['pos.session'].create({'config_id': self.config.id, 'user_id': self.env.uid})
        session.set_opening_control(0, '')
        session.try_cash_in_out('in', cash, 'sales', {'translatedType': 'in', 'formattedAmount': str(cash)})
        session.post_closing_cash_details(cash)
        session.close_session_from_ui()
        return session

    # ------------------------------------------------------------------

    def test_access_and_files(self):
        self.assertTrue(self.owner_user.share, 'The owner gets a free portal login')
        self.assertEqual(self._api('home', box_id=self.box.id)['code'], 'login')
        self.assertFalse(self._api('session')['logged'])
        self.assertEqual(self._api('login', login='ali_owner_app', password='wrong')['code'], 'login')
        info = self._login()
        self.assertEqual([b['box_id'] for b in info['boxes']], [self.box.id])
        self.assertEqual(self._api('home', box_id=self.other_box.id)['code'], 'forbidden')
        page = self.url_open('/ecc/owner/app')
        self.assertIn('manifest.webmanifest', page.text)
        manifest = self.url_open('/ecc/owner/manifest.webmanifest').json()
        self.assertEqual(manifest['scope'], '/ecc/owner/')
        sw = self.url_open('/ecc/owner/sw.js')
        self.assertEqual(sw.headers.get('Service-Worker-Allowed'), '/ecc/owner/')
        self.assertNotIn('{{', sw.text)
        self._api('logout')
        self.assertEqual(self._api('home', box_id=self.box.id)['code'], 'login')

    def test_record_everything_like_the_bot(self):
        session = self._closed_session(100000.0)
        self._login()
        home = self._api('home', box_id=self.box.id)
        self.assertEqual([s['session_id'] for s in home['sessions']], [session.id])

        result = self._api('collect', box_id=self.box.id, session_id=session.id, request_uid='collect-req-0001')
        self.assertEqual(result['card']['balance'], 100000.0)
        again = self._api('collect', box_id=self.box.id, session_id=session.id, request_uid='collect-req-0001')
        self.assertTrue(again['replayed'], 'A retry after a lost answer is not a second collection')
        self.assertEqual(again['card']['balance'], 100000.0)
        self.assertEqual(self.box.move_ids.source, 'app')

        categories = self._api('categories', box_id=self.box.id)['categories']
        self.assertIn(self.category.id, [c['id'] for c in categories])
        expense = self._api('expense', box_id=self.box.id, amount=25000, category_id=self.category.id,
                            note='Generator diesel', request_uid='expense-req-0001',
                            photos=[{'content_b64': PHOTO, 'mimetype': 'image/jpeg'}])
        self.assertEqual(expense['card']['balance'], 75000.0)
        receipt = self.env['ecc.receipt'].search([('owner_box_id', '=', self.box.id)])
        self.assertEqual((receipt.paid_by, receipt.state, len(receipt.photo_ids)), ('owner', 'to_review', 1))
        self.assertIn('Owner App', receipt.expense_id.notes)

        self.assertEqual(self._api('took', box_id=self.box.id, amount=5000, request_uid='took-req-00001')
                         ['card']['balance'], 70000.0)
        self.assertEqual(self._api('deposit', box_id=self.box.id, amount=10000, target='bank',
                                   request_uid='deposit-req-001')['card']['balance'], 60000.0)
        refused = self._api('took', box_id=self.box.id, amount=-3)
        self.assertEqual(refused['code'], 'refused')

        count = self._api('count', box_id=self.box.id, counted=59000)
        self.assertEqual(count['difference'], -1000.0)
        moves = self._api('moves', box_id=self.box.id)['moves']
        self.assertEqual([m['type'] for m in moves], ['deposit', 'drawing', 'expense', 'collect'])
        self.assertEqual(moves[0]['balance_after'], 60000.0)

    def test_statement_in_the_app(self):
        self.box.statement_frequency = 'weekly'
        statement = self.box._create_statement(fields.Date.today() - timedelta(days=7), fields.Date.today())
        statement._send()
        self.assertEqual(statement.state, 'sent', 'Without Telegram the statement waits in the app')
        self.platform.assert_not_called()
        self._login()
        self.assertEqual(self._api('home', box_id=self.box.id)['pending_statements'], 1)
        listed = self._api('statements', box_id=self.box.id)['statements']
        self.assertTrue(listed[0]['can_answer'])
        answer = self._api('statement_answer', box_id=self.box.id, statement_id=statement.id, correct=False,
                           note='Missing 5,000')
        self.assertEqual(statement.state, 'disputed')
        self.assertFalse(answer['statements'][0]['can_answer'])
        self.assertEqual(self._api('statement_answer', box_id=self.box.id, statement_id=statement.id,
                                   correct=True)['code'], 'refused')
