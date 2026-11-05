# -*- coding: utf-8 -*-
import base64
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import Form, tagged

from odoo.addons.donialink_agent.models.agent_registry import ToolError
from odoo.addons.expense_cash_control.tests.common import ExpenseCashCommon

PHOTO = base64.b64encode(b'\x89PNG\r\n\x1a\n-ecc-owner-expense').decode()
OWNER_TG = '5550001'


@tagged('post_install', '-at_install')
class TestOwnerBox(ExpenseCashCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Account = cls.env['account.account']
        cls.drawings = Account.create({'name': 'ECC Owner Drawings', 'code': 'ECC3100', 'account_type': 'equity'})
        cls.transfer = Account.create({'name': 'ECC Transfer', 'code': 'ECC1999', 'account_type': 'asset_current',
                                       'reconcile': True})
        cls.company.transfer_account_id = cls.transfer
        cls.cash_journal.write({
            'loss_account_id': Account.create({'name': 'ECC Loss', 'code': 'ECC6998', 'account_type': 'expense'}).id,
            'profit_account_id': Account.create({'name': 'ECC Gain', 'code': 'ECC7998',
                                                 'account_type': 'income_other'}).id,
        })
        cls.cash_method = cls.env['pos.payment.method'].create({'name': 'ECC Cash', 'journal_id': cls.cash_journal.id})
        cls.config = cls.env['pos.config'].create({
            'name': 'ECC Owner POS', 'payment_method_ids': [(6, 0, cls.cash_method.ids)],
        })
        cls.box = cls.env['ecc.owner.box'].create({
            'name': 'Ali', 'drawings_account_id': cls.drawings.id, 'till_journal_id': cls.cash_journal.id,
            'collect_from': fields.Date.today() - timedelta(days=1),
        })
        cls.box.telegram_user_id = OWNER_TG
        cls.category.owner_expense = True
        cls.tools = cls.env['donialink.agent.tools']

    def setUp(self):
        super().setUp()
        patcher = patch.object(type(self.env['telegram.service']), 'donialink_post',
                               return_value={'ok': True, 'delivered': True, 'url': 'https://t.me/dlbot?start=X'})
        self.platform = patcher.start()
        self.addCleanup(patcher.stop)

    def _tool(self, name, **params):
        params.setdefault('box_id', self.box.id)
        params.setdefault('telegram_user_id', OWNER_TG)
        return self.tools._run_tool(name, params)[1]

    def _closed_session(self, cash_in=100000.0, cash_out_category=None, cash_out=0.0):
        session = self.env['pos.session'].create({'config_id': self.config.id, 'user_id': self.env.uid})
        session.set_opening_control(0, '')
        session.try_cash_in_out('in', cash_in, 'sales cash', {'translatedType': 'in', 'formattedAmount': str(cash_in)})
        if cash_out:
            extras = {'translatedType': 'out', 'formattedAmount': str(cash_out)}
            if cash_out_category:
                extras['expense_category_id'] = cash_out_category.id
            session.try_cash_in_out('out', cash_out, 'owner', extras)
        session.post_closing_cash_details(cash_in - cash_out)
        session.close_session_from_ui()
        self.assertEqual(session.state, 'closed')
        return session

    # ------------------------------------------------------------------

    def test_setup_and_link(self):
        self.assertEqual(self.box.journal_id.type, 'cash')
        self.assertEqual(self.box.collection_category_id.account_id, self.box.journal_id.default_account_id)
        self.assertTrue(self.box.collection_category_id.available_in_pos)
        box2 = self.env['ecc.owner.box'].create({'name': 'Omar', 'drawings_account_id': self.drawings.id})
        self.assertNotEqual(box2.journal_id, self.box.journal_id, 'Each partner has his own box')
        box2.action_generate_link()
        self.assertEqual(self.platform.call_args.args[0], 'telegram/owner-link')
        self.assertTrue(box2.link_code)
        self.assertEqual(box2.link_url, 'https://t.me/dlbot?start=X')
        card = self.tools._run_tool('owner_link', {'code': box2.link_code, 'telegram_user_id': '777',
                                                   'name': 'Omar'})[1]
        self.assertEqual(card['box_id'], box2.id)
        self.assertTrue(box2.is_linked)
        self.assertFalse(box2.link_code, 'A code works once')
        self.assertEqual([b['box_id'] for b in self.tools._run_tool(
            'owner_boxes', {'telegram_user_id': '777'})[1]['boxes']], [box2.id])
        with self.assertRaises(ToolError) as error:
            self._tool('owner_card', box_id=box2.id)   # Ali's Telegram id on Omar's box
        self.assertEqual(error.exception.code, 'not_linked')

    def test_collect_from_bot_full_and_partial(self):
        session = self._closed_session(100000.0)
        kinds = [c.args[1]['kind'] for c in self.platform.call_args_list if c.args[0] == 'telegram/owner']
        self.assertIn('session_closed', kinds, 'The owner is asked to collect when the session closes')
        self.assertEqual(session.owner_collection_state, 'none')
        sessions = self._tool('owner_sessions')['sessions']
        self.assertEqual([s['session_id'] for s in sessions], [session.id])
        self.assertEqual(sessions[0]['amount'], 100000.0)

        card = self._tool('owner_collect', session_id=session.id, amount=60000.0)
        self.assertEqual(card['balance'], 60000.0)
        self.assertEqual(session.owner_collection_state, 'partial')
        difference = session.owner_difference_ids
        self.assertEqual((difference.kind, difference.amount, difference.state), ('collection', 40000.0, 'pending'))
        with self.assertRaises(ToolError) as error:
            self._tool('owner_collect', session_id=session.id, amount=50000.0)
        self.assertEqual(error.exception.code, 'refused')

        self._tool('owner_collect', session_id=session.id)   # the rest
        self.assertEqual(session.owner_collection_state, 'collected')
        self.assertEqual(difference.state, 'cancelled')
        self.assertEqual(self.box.balance, 100000.0)
        self.assertEqual(self.box.account_balance, 100000.0, 'Books and box agree')
        self.assertIn('Collected by Ali', session.owner_collection_text)
        self.assertFalse(self._tool('owner_sessions')['sessions'])

    def test_partial_left_in_till(self):
        session = self._closed_session(50000.0)
        self._tool('owner_collect', session_id=session.id, amount=40000.0)
        difference = session.owner_difference_ids
        difference.resolution = 'left_in_till'
        difference.action_resolve()
        self.assertEqual(session.owner_collection_state, 'collected')

    def test_collect_with_pos_cash_out(self):
        self.config.use_cash_categories = True
        session = self._closed_session(80000.0, cash_out_category=self.box.collection_category_id, cash_out=70000.0)
        self.assertEqual(self.box.balance, 70000.0)
        self.assertEqual(self.box.move_ids.source, 'pos')
        self.assertEqual(session.owner_collection_state, 'collected', 'The 10,000 left is the float')

    def test_expense_review_and_reject(self):
        categories = self._tool('owner_categories')['categories']
        self.assertEqual([c['id'] for c in categories], [self.category.id])
        card = self._tool('owner_expense', amount=7500.0, category_id=self.category.id, note='generator oil',
                          chat_id=OWNER_TG, message_id=10, photos=[{'content_b64': PHOTO}])
        self.assertEqual(card['balance'], -7500.0)
        self.assertEqual(card['business_owes_owner'], 7500.0)
        receipt = self.env['ecc.receipt'].browse(card['receipt_id'])
        self.assertEqual((receipt.paid_by, receipt.state, receipt.owner_box_id), ('owner', 'to_review', self.box))
        expense = receipt.expense_id
        self.assertEqual(expense.journal_id, self.box.journal_id)
        self.assertEqual(expense.payment_mode, 'paid')
        self.assertTrue(expense.attachment_ids)
        expense.amount = 8000.0   # the accountant fixes the amount
        self.assertEqual(self.box.balance, -8000.0)
        receipt.action_reject()
        self.assertFalse(expense.exists())
        self.assertEqual(self.box.balance, 0.0)

    def test_expense_converted_to_purchase_order(self):
        card = self._tool('owner_expense', amount=5000.0, category_id=self.category.id)
        receipt = self.env['ecc.receipt'].browse(card['receipt_id'])
        receipt.partner_id = self.vendor
        action = receipt.action_create_purchase_order()
        product = self.env['product.product'].create({'name': 'ECC Sugar', 'type': 'consu'})
        form = Form(self.env['purchase.order'].with_context(action['context']))
        with form.order_line.new() as line:
            line.product_id = product
            line.product_qty = 1
            line.price_unit = 5000.0
            line.taxes_id.clear()
        order = form.save()
        self.assertEqual(receipt.purchase_order_id, order)
        self.assertFalse(receipt.expense_id)
        self.assertEqual(self.box.balance, 0.0)
        order.button_confirm()
        order.order_line.qty_received = 1
        order.action_create_invoice()
        bill = order.invoice_ids
        bill.invoice_date = fields.Date.today()
        bill.action_post()
        wizard = self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=bill.ids).create({'journal_id': self.box.journal_id.id})
        wizard.action_create_payments()
        self.assertEqual(self.box.balance, -5000.0, 'Paying the bill from his cash lowers his box')

    def test_took_deposit_moves_count_statement(self):
        session = self._closed_session(100000.0)
        self._tool('owner_collect', session_id=session.id)
        took = self._tool('owner_took', amount=20000.0)
        self.assertEqual(took['balance'], 80000.0)
        drawing = self.box.move_ids.filtered(lambda m: m.kind == 'drawing')
        self.assertIn(self.drawings, drawing.account_move_id.line_ids.account_id)
        self._tool('owner_deposit', amount=30000.0, target='bank')
        self._tool('owner_deposit', amount=10000.0, target='till')
        self.assertEqual(self.box.balance, 40000.0)
        self.assertEqual(self.box.account_balance, 40000.0)
        moves = self._tool('owner_moves', limit=10)
        self.assertEqual(moves['moves'][0]['balance_after'], 40000.0)
        self.assertEqual(moves['moves'][-1]['balance_after'], 100000.0)

        count = self._tool('owner_count', counted=38000.0)
        self.assertEqual(count['difference'], -2000.0)
        difference = self.box.difference_ids.filtered(lambda d: d.kind == 'count')
        difference.write({'resolution': 'loss', 'category_id': self.category.id})
        difference.action_resolve()
        self.assertEqual(self.box.balance, 38000.0)
        self.assertEqual(self._tool('owner_count', counted=38000.0)['difference'], 0.0)

        self.box.action_send_statement()
        statement = self.box.statement_ids[:1]
        self.assertEqual(statement.state, 'sent')
        self.assertEqual((statement.collected, statement.took, statement.deposited, statement.closing),
                         (100000.0, 20000.0, 40000.0, 38000.0))
        self._tool('owner_statement_answer', statement_id=statement.id, correct=False, note='I had 40,000')
        self.assertEqual(statement.state, 'disputed')
        self.assertTrue(self.box.difference_ids.filtered(lambda d: d.kind == 'statement'))

    def test_statement_due(self):
        self.box.write({'statement_frequency': 'weekly', 'statement_weekday': '4'})
        friday = fields.Date.from_string('2026-11-06')
        self.assertEqual(self.box._statement_due(friday), (friday - timedelta(days=7), friday - timedelta(days=1)))
        self.assertIsNone(self.box._statement_due(friday + timedelta(days=1)))
        self.box.statement_frequency = 'monthly'
        first = fields.Date.from_string('2026-12-01')
        self.assertEqual(self.box._statement_due(first)[1], fields.Date.from_string('2026-11-30'))

    def test_statement_not_delivered(self):
        self.platform.return_value = {'ok': True, 'delivered': False, 'message': 'blocked the bot'}
        self.box.action_send_statement()
        self.assertEqual(self.box.statement_ids[:1].state, 'draft', 'Only a delivered statement waits for the owner')
        self.platform.side_effect = UserError('not_linked')
        self.box.statement_frequency = 'weekly'
        with patch.object(type(self.box), '_statement_due', lambda box, today: (today, today)):
            self.env['ecc.owner.box']._cron_owner_statements()   # no exception
        self.assertEqual(self.box.statement_ids[:1].state, 'draft')

    def test_amount_must_be_positive(self):
        with self.assertRaises(ToolError):
            self._tool('owner_took', amount=0.0)
        no_till = self.env['ecc.owner.box'].create({'name': 'No Till', 'drawings_account_id': self.drawings.id})
        with self.assertRaises(UserError):
            no_till._record_deposit(5.0, 'till')
