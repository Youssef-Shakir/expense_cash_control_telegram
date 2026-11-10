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

    def test_classified_cash_out_in_expenses_summary(self):
        """The DoniaLink app's expenses list shows a POS cash-out classified to a category."""
        session = self._open_session()
        move = self._cash_out(session, 35.0, 'ice blocks')
        move.category_id = self.category
        move.action_classify()
        today = str(move.date)
        params = {'date_from': today, 'date_to': today, 'entries': 50}
        result = self.tools._run_tool('expenses_summary', params)[1]
        pos = [e for e in result['entries'] if e['source'] == 'pos' and e['id'] == move.id]
        self.assertEqual(len(pos), 1)
        self.assertEqual((pos[0]['name'], pos[0]['amount'], pos[0]['category'], pos[0]['pos']),
                         ('ice blocks', 35.0, self.category.name, self.config.name))
        self.assertGreaterEqual(result['pos_cash_outs'], 1)
        without = self.tools._run_tool('expenses_summary', dict(params, include_pos_cash_outs=False))[1]
        self.assertAlmostEqual(result['total'] - without['total'], result['pos_cash_out_total'])

    def test_vendor_payment_and_purchase_order(self):
        """The cashier paid a vendor from the drawer (even a receipt marked payable): the cash-out goes on the
        vendor account, the products go in a purchase order and its bill is paid by the cash-out."""
        session = self._open_session()
        move = self._cash_out(session, 50.0, 'flour')
        move.category_id = self.category
        move.action_classify()   # classified as an expense at the POS: reclassified as a vendor payment
        sent_at = fields.Datetime.to_string(fields.Datetime.now() + timedelta(minutes=1)) + 'Z'
        receipt = self._receipt(self._send(90, sent_at=sent_at))
        receipt.write({'paid_by': 'payable', 'amount': 50.0})
        self.assertIn(move, receipt.suggested_cash_move_ids, 'payable receipts can be matched too')

        with self.assertRaises(UserError):
            move.with_context(ecc_receipt_id=receipt.id).action_pay_vendor_receipt()   # no vendor yet
        receipt.partner_id = self.vendor
        action = move.with_context(ecc_receipt_id=receipt.id).action_pay_vendor_receipt()
        self.assertEqual(action['res_model'], 'purchase.order')
        self.assertEqual((move.state, move.classification_type, move.partner_id),
                         ('classified', 'partner', self.vendor))
        self.assertEqual((receipt.state, receipt.cash_move_id), ('processed', move))
        self.assertTrue(receipt.vendor_payment)
        payable = self.vendor.property_account_payable_id
        self.assertTrue(move.statement_line_id.move_id.line_ids.filtered(lambda l: l.account_id == payable))

        product = self.env['product.product'].create({'name': 'ECC Flour', 'purchase_method': 'purchase'})
        order = self.env['purchase.order'].with_context(action['context']).create({
            'partner_id': self.vendor.id,
            'order_line': [(0, 0, {'product_id': product.id, 'product_qty': 2, 'price_unit': 25.0, 'taxes_id': []})],
        })
        self.assertEqual(receipt.purchase_order_id, order)
        order.button_confirm()
        order.action_create_invoice()
        bill = order.invoice_ids
        bill.invoice_date = fields.Date.today()
        bill.action_post()
        self.assertIn(bill.payment_state, ('paid', 'in_payment'), 'the cash-out paid the bill')
        self.assertEqual(move.bill_id, bill)

    def test_rejected_receipt_frees_the_cash_out(self):
        session = self._open_session()
        move = self._cash_out(session, 20.0, 'bread')
        sent_at = fields.Datetime.to_string(fields.Datetime.now() + timedelta(minutes=1)) + 'Z'
        wrong = self._receipt(self._send(80, sent_at=sent_at))
        wrong.write({'paid_by': 'cashier', 'amount': 20.0, 'cash_move_id': move.id})
        self.assertEqual(move.receipt_count, 1)
        wrong.action_reject()
        self.assertEqual(move.receipt_count, 0, 'a rejected photo proves nothing')
        right = self._receipt(self._send(81, content=PNG_B, sent_at=sent_at))
        right.write({'paid_by': 'cashier', 'amount': 20.0})
        self.assertIn(move, right.suggested_cash_move_ids)

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
        # a cash-out that already has its receipt is not offered again
        self.assertEqual(unmatched.suggested_cash_move_ids, other)
        self.assertNotIn(move, self.env['pos.cash.move'].search([('receipt_count', '=', 0)]))
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
