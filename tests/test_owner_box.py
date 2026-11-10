# -*- coding: utf-8 -*-
import base64
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessError, UserError
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

    def test_return_collection_by_mistake(self):
        session = self._closed_session(100000.0)
        self._tool('owner_collect', session_id=session.id)
        move = self.box.move_ids
        self.assertEqual(self.box.balance, 100000.0)
        with self.assertRaises(UserError):
            move._return_to_till('  ')
        wizard = self.env['ecc.owner.collection.return'].with_context(
            **move.action_return_cash()['context']).create({'reason': 'Wrong partner'})
        self.assertEqual(wizard.journal_id, session.cash_journal_id)
        wizard.action_confirm()
        self.assertEqual(move.state, 'returned')
        self.assertEqual(move.return_statement_line_id.amount, 100000.0, 'The cash is back in the till')
        self.assertEqual(move.return_statement_line_id.journal_id, session.cash_journal_id)
        self.assertEqual(self.box.balance, 0.0)
        self.assertEqual(self.box.account_balance, 0.0, 'Books and box agree')
        self.assertEqual(session.owner_collection_state, 'none')
        self.assertEqual(session.owner_remaining_amount, 100000.0, 'The session can be collected again')
        with self.assertRaises(UserError):
            move._return_to_till('twice')
        self._tool('owner_collect', session_id=session.id)
        self.assertEqual(self.box.balance, 100000.0)

    def test_return_pos_cash_out_collection(self):
        self.config.use_cash_categories = True
        session = self._closed_session(80000.0, cash_out_category=self.box.collection_category_id, cash_out=70000.0)
        move = self.box.move_ids
        move._return_to_till('Cashier picked the owner category by mistake')
        self.assertEqual(self.box.balance, 0.0)
        self.assertEqual(self.box.account_balance, 0.0)
        self.assertEqual(session.owner_remaining_amount, 80000.0, 'Float + the returned cash')
        with self.assertRaises(UserError):
            move.cash_move_id.action_reset()

    def test_return_only_for_accountant(self):
        session = self._closed_session(30000.0)
        self._tool('owner_collect', session_id=session.id)
        move = self.box.move_ids
        user = self.env['res.users'].create({
            'name': 'ECC Clerk', 'login': 'ecc_clerk_return',
            'groups_id': [(6, 0, [self.env.ref('expense_cash_control.group_expense_user').id,
                                  self.env.ref('base.group_user').id])],
        })
        with self.assertRaises(AccessError):
            move.with_user(user).action_return_cash()

    def test_expense_review_and_reject(self):
        categories = self._tool('owner_categories')['categories']
        self.assertEqual([c['id'] for c in categories], [self.category.id])
        card = self._tool('owner_expense', amount=7500.0, category_id=self.category.id, note='generator oil',
                          chat_id=OWNER_TG, message_id=10, photos=[{'content_b64': PHOTO}])
        self.assertEqual(card['balance'], -7500.0)
        self.assertEqual(card['business_owes_owner'], 7500.0)
        self.assertIsNone(card['receipt_id'], 'an owner expense is cash, not a receipt')
        self.assertFalse(self.env['ecc.receipt'].search([('owner_box_id', '=', self.box.id)]))
        move = self.box.move_ids.filtered(lambda m: m.kind == 'expense')
        self.assertEqual(move.review_state, 'to_review')
        self.assertEqual(self.box.receipt_to_review_count, 1)
        expense = move.expense_id
        self.assertEqual(expense.journal_id, self.box.journal_id)
        self.assertEqual(expense.payment_mode, 'paid')
        self.assertTrue(expense.attachment_ids)
        self.assertEqual(move.attachment_ids, expense.attachment_ids)
        expense.amount = 8000.0   # the accountant fixes the amount
        self.assertEqual(self.box.balance, -8000.0)
        move.action_review_reject()
        self.assertFalse(expense.exists())
        self.assertEqual((move.review_state, move.state), ('rejected', 'cancelled'))
        self.assertEqual(self.box.balance, 0.0)

    def test_expense_reviewed(self):
        self._tool('owner_expense', amount=3000.0, category_id=self.category.id)
        move = self.box.move_ids.filtered(lambda m: m.kind == 'expense')
        move.action_review_done()
        self.assertEqual(move.review_state, 'reviewed')
        self.assertEqual(self.box.balance, -3000.0)
        with self.assertRaises(UserError):
            move.action_review_reject()

    def test_expense_as_vendor_payment(self):
        """The owner paid a supplier: no purchase order, the amount goes on the vendor account and pays his bill."""
        self._tool('owner_expense', amount=5000.0, category_id=self.category.id)
        move = self.box.move_ids.filtered(lambda m: m.kind == 'expense')
        move.review_as = 'vendor'
        with self.assertRaises(UserError):
            move.action_review_confirm()   # no vendor yet
        move.vendor_id = self.vendor
        self.assertTrue(move.action_review_confirm())
        self.assertEqual((move.review_state, move.review_as), ('reviewed', 'vendor'))
        self.assertFalse(move.expense_id, 'the expense is replaced, never booked twice')
        self.assertFalse(self.env['purchase.order'].search([('partner_id', '=', self.vendor.id)]))
        self.assertEqual(self.box.balance, -5000.0, 'the owner paid it: his balance does not change')

        bill = self.env['account.move'].create({
            'move_type': 'in_invoice', 'partner_id': self.vendor.id, 'invoice_date': fields.Date.today(),
            'invoice_line_ids': [(0, 0, {'name': 'Sugar', 'quantity': 1, 'price_unit': 5000.0, 'tax_ids': []})],
        })
        bill.action_post()
        offered = [c for c in bill.invoice_outstanding_credits_debits_widget['content']
                   if c['move_id'] == move.vendor_entry_id.id]
        self.assertEqual(len(offered), 1, "the owner's payment is offered on the vendor's bill")
        bill.js_assign_outstanding_line(offered[0]['id'])
        self.assertIn(bill.payment_state, ('paid', 'in_payment'))
        self.assertEqual(self.box.account_balance, -5000.0)

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
