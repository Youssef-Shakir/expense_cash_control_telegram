# -*- coding: utf-8 -*-
import base64
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import Form, tagged

from odoo.addons.donialink_agent.models.agent_registry import ToolError
from odoo.addons.expense_cash_control.tests.common import ExpenseCashCommon

PNG_A = base64.b64encode(b'\x89PNG\r\n\x1a\n-ecc-test-receipt-A').decode()
PNG_B = base64.b64encode(b'\x89PNG\r\n\x1a\n-ecc-test-receipt-B').decode()
CHAT = '-1001234'


@tagged('post_install', '-at_install')
class TestTelegramReceipt(ExpenseCashCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.cash_method = cls.env['pos.payment.method'].create({
            'name': 'ECC Cash', 'journal_id': cls.cash_journal.id,
        })
        cls.config = cls.env['pos.config'].create({
            'name': 'ECC Receipt POS', 'payment_method_ids': [(6, 0, cls.cash_method.ids)],
        })
        cls.tools = cls.env['donialink.agent.tools']

    # helpers ------------------------------------------------------------

    def _open_session(self):
        session = self.env['pos.session'].create({'config_id': self.config.id, 'user_id': self.env.uid})
        session.set_opening_control(0, '')
        return session

    def _cash_out(self, session, amount, reason):
        session.try_cash_in_out('out', amount, reason, {'translatedType': 'out', 'formattedAmount': str(amount)})
        return session.cash_move_ids.sorted('id')[-1:]

    def _send(self, message_id, content=PNG_A, user='111', media_group_id=None, file_unique_id=None, **kw):
        params = {
            'company_id': self.company.id, 'chat_id': CHAT, 'chat_title': 'Cafe staff',
            'message_id': message_id, 'media_group_id': media_group_id,
            'sender': {'telegram_user_id': user, 'name': 'Ali', 'username': 'ali'},
            'photo': {'content_b64': content, 'file_unique_id': file_unique_id and 'test-%s' % file_unique_id, 'mimetype': 'image/png'},
        }
        params.update(kw)
        _meta, result = self.tools._run_tool('receipt_create', params)
        return result

    def _receipt(self, result):
        return self.env['ecc.receipt'].browse(result['receipt_id'])

    # tools --------------------------------------------------------------

    def test_create_album_idempotent(self):
        first = self._send(10, media_group_id='alb1', file_unique_id='u1', caption='gas cylinder')
        self.assertTrue(first['is_new_receipt'])
        self.assertTrue(first['reference'].startswith('R-'))
        receipt = self._receipt(first)
        self.assertEqual(receipt.state, 'to_review')
        self.assertEqual(receipt.paid_by, 'unspecified')
        self.assertEqual(receipt.note, 'gas cylinder')
        self.assertEqual(receipt.sender_id.name, 'Ali')

        second = self._send(11, content=PNG_B, media_group_id='alb1', file_unique_id='u2')
        self.assertFalse(second['is_new_receipt'])
        self.assertEqual(second['receipt_id'], receipt.id)
        self.assertEqual(receipt.photo_count, 2)
        self.assertIsNone(second['duplicate_of'])

        again = self._send(11, content=PNG_B, media_group_id='alb1')
        self.assertFalse(again['is_new_receipt'])
        self.assertEqual(receipt.photo_count, 2, 'A message sent twice is stored once')

    def test_duplicate_by_file_unique_id_and_checksum(self):
        original = self._receipt(self._send(20, file_unique_id='same'))
        forwarded = self._send(21, content=PNG_B, file_unique_id='same')
        self.assertEqual(forwarded['duplicate_of']['id'], original.id)
        same_bytes = self._send(22, file_unique_id='other')
        self.assertEqual(same_bytes['duplicate_of']['id'], original.id)
        self.assertNotIn('again', forwarded['summary_text'])

    def test_archived_sender_ignored(self):
        receipt = self._receipt(self._send(30))
        receipt.sender_id.active = False
        with self.assertRaises(ToolError) as error:
            self._send(31, content=PNG_B)
        self.assertEqual(error.exception.code, 'sender_ignored')

    def test_update_only_by_sender(self):
        receipt = self._receipt(self._send(40))
        _meta, result = self.tools._run_tool('receipt_update', {
            'receipt_id': receipt.id, 'telegram_user_id': '111', 'paid_by': 'cashier', 'note': 'ice'})
        self.assertEqual(receipt.paid_by, 'cashier')
        self.assertEqual(receipt.note, 'ice')
        self.assertIn('Cashier', result['summary_text'])
        self.assertIn(receipt.name, result['summary_text'])
        with self.assertRaises(ToolError) as error:
            self.tools._run_tool('receipt_update', {
                'receipt_id': receipt.id, 'telegram_user_id': '999', 'paid_by': 'payable'})
        self.assertEqual(error.exception.code, 'not_the_sender')
        self.assertEqual(receipt.paid_by, 'cashier')

    def test_question_and_reply(self):
        receipt = self._receipt(self._send(50))
        with patch.object(type(self.env['telegram.service']), 'send_reply', return_value=777) as send:
            wizard = self.env['ecc.receipt.question.wizard'].create({'receipt_id': receipt.id, 'text': 'Amount?'})
            wizard.action_send()
        send.assert_called_once()
        self.assertEqual(send.call_args.args[:2], (CHAT, 50))
        self.assertEqual(receipt.question_state, 'waiting')

        self.tools._run_tool('receipt_reply', {
            'company_id': self.company.id, 'chat_id': CHAT, 'reply_to_message_id': 777, 'message_id': 778,
            'sender': {'telegram_user_id': '111', 'name': 'Ali'}, 'text': '25000'})
        self.assertEqual(receipt.question_state, 'answered')
        self.assertEqual(receipt.question_ids.answer, '25000')
        self.assertIn('25000', receipt.message_ids[0].body)

        # a reply under the photo itself also lands on the receipt
        _meta, result = self.tools._run_tool('receipt_reply', {
            'company_id': self.company.id, 'chat_id': CHAT, 'reply_to_message_id': 50,
            'sender': {'telegram_user_id': '222', 'name': 'Omar'}, 'text': 'from the market'})
        self.assertEqual(result['receipt_id'], receipt.id)
        with self.assertRaises(ToolError) as error:
            self.tools._run_tool('receipt_reply', {
                'company_id': self.company.id, 'chat_id': CHAT, 'reply_to_message_id': 9999,
                'sender': {'telegram_user_id': '111'}, 'text': 'hello'})
        self.assertEqual(error.exception.code, 'not_found')

    # accountant ---------------------------------------------------------

    def test_create_bill_from_payable_receipt(self):
        receipt = self._receipt(self._send(60, caption='flour'))
        receipt.write({'paid_by': 'payable', 'amount': 120.0, 'category_id': self.category.id,
                       'partner_id': self.vendor.id})
        action = receipt.action_create_bill()
        form = Form(self.env['expense.express'].with_context(action['context']))
        self.assertEqual(form.payment_mode, 'to_pay')
        self.assertEqual(form.name, 'flour')
        self.assertEqual(form.amount, 120.0)
        expense = form.save()
        self.assertEqual(receipt.expense_id, expense)
        self.assertEqual(receipt.state, 'processed')
        self.assertEqual(len(expense.attachment_ids), 1)
        self.assertEqual(expense.move_id.move_type, 'in_invoice')
        self.assertNotEqual(expense.move_id.name, 'flour', 'Prefill must not leak into the bill')

    def test_match_cash_out_classifies_and_review_rule(self):
        session = self._open_session()
        move = self._cash_out(session, 30.0, 'gas')
        other = self._cash_out(session, 12.0, 'ice')
        self.assertEqual(move.state, 'to_classify')
        receipt = self._receipt(self._send(70, sent_at=fields.Datetime.to_string(
            fields.Datetime.now() + timedelta(minutes=1)) + 'Z'))
        self.assertEqual(receipt.session_id, session, 'The only running session is guessed')
        receipt.write({'paid_by': 'cashier', 'amount': 30.0})
        self.assertEqual(receipt.suggested_cash_move_ids[:1], move, 'Closest amount first')

        with self.assertRaises(UserError):
            move.with_context(ecc_receipt_id=receipt.id).action_match_receipt()  # no category yet
        receipt.category_id = self.category
        move.with_context(ecc_receipt_id=receipt.id).action_match_receipt()
        self.assertEqual(receipt.state, 'processed')
        self.assertEqual(receipt.cash_move_id, move)
        self.assertEqual(move.state, 'classified')
        self.assertEqual(move.category_id, self.category)
        self.assertEqual(move.receipt_count, 1)
        self.assertTrue(self.env['ir.attachment'].search_count(
            [('res_model', '=', 'pos.cash.move'), ('res_id', '=', move.id)]))
        self.assertFalse(receipt.amount_mismatch)

        self.assertEqual(session.cash_out_without_receipt_count, 1)  # "ice"
        unmatched = self._receipt(self._send(71, content=PNG_B))
        unmatched.paid_by = 'cashier'
        self.assertEqual(unmatched.session_id, session)
        self.assertEqual(session.receipt_unmatched_count, 1)

        session.post_closing_cash_details(-42.0)
        session.close_session_from_ui()
        other.category_id = self.category
        other.action_classify()
        self.config.cash_out_receipt_required = True
        with self.assertRaises(UserError):
            session.action_cash_review_done()
        unmatched.amount = 13.0
        unmatched._match_cash_move(other)
        self.assertTrue(unmatched.amount_mismatch)
        self.assertEqual(session.cash_out_without_receipt_count, 0)
        self.assertEqual(session.receipt_unmatched_count, 0)
        session.action_cash_review_done()
        self.assertEqual(session.cash_review_state, 'reviewed')

    def test_reject_and_reset(self):
        receipt = self._receipt(self._send(80))
        receipt.action_reject()
        self.assertEqual(receipt.state, 'rejected')
        with self.assertRaises(UserError):
            receipt.action_mark_duplicate()
        receipt.action_reset_to_review()
        self.assertEqual(receipt.state, 'to_review')

    def test_dashboard(self):
        Dashboard = self.env['expense.cash.dashboard']
        before = Dashboard.get_dashboard_data()['receipts_to_review']
        self._send(90)
        self.assertEqual(Dashboard.get_dashboard_data()['receipts_to_review'], before + 1)

    def test_purchase_order_from_payable_receipt(self):
        receipt = self._receipt(self._send(100, caption='flour 10 bags'))
        receipt.write({'paid_by': 'payable', 'partner_id': self.vendor.id})
        action = receipt.action_create_purchase_order()
        product = self.env['product.product'].create({'name': 'ECC Flour', 'type': 'consu', 'standard_price': 5.0})
        form = Form(self.env['purchase.order'].with_context(action['context']))
        self.assertEqual(form.partner_id, self.vendor)
        self.assertEqual(form.origin, receipt.name)
        with form.order_line.new() as line:
            line.product_id = product
            line.product_qty = 10
            line.price_unit = 5.0
            line.taxes_id.clear()
        order = form.save()
        self.assertEqual(receipt.purchase_order_id, order)
        self.assertEqual(receipt.state, 'processed')
        self.assertEqual(order.state, 'draft', 'An RFQ the accountant confirms')
        self.assertTrue(self.env['ir.attachment'].search_count(
            [('res_model', '=', 'purchase.order'), ('res_id', '=', order.id)]))
        receipt.amount = 50.0
        self.assertFalse(receipt.amount_mismatch)
        order.button_confirm()
        order.order_line.qty_received = 10
        order.action_create_invoice()
        bill = order.invoice_ids
        self.assertTrue(bill)
        self.assertTrue(self.env['ir.attachment'].search_count(
            [('res_model', '=', 'account.move'), ('res_id', '=', bill.id)]), 'The bill gets the photo')
